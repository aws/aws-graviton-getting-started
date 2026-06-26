# Groovy on Graviton: tuning tips

## TL;DR

If a Groovy app shows a per-thread regression on Graviton vs equivalent x86 instances, it is most often paying for Groovy's dynamic dispatch on every hot call. Capture an on-CPU flame graph with `async-profiler`. If frames like `MetaClassImpl.invokeMethod`, `CachedMethod.invoke`, `java.lang.reflect.Method.invoke`, or (on Groovy 4+) `Invokers$Holder.linkToCallSite` and `LambdaForm$MH.*` dominate your hot path, annotate the relevant classes with `@CompileStatic`, give parameters concrete types, and replace closure-based iteration (`findAll`, `any`, `each`) with `for` loops in those classes. This typically recovers a large fraction of the gap and, for dispatch-bound workloads, can match or exceed the original x86 baseline.

## Background

Groovy applications running on AWS Graviton (M6g, M7g, C7g, M8g, etc) sometimes show worse per-thread CPU performance than the equivalent x86 instance, even with the same JVM and the same application. In most cases this is not a Groovy-specific bug. It's the cost of Groovy's dynamic method dispatch behaving differently on aarch64 than on x86_64.

Groovy resolves most method calls through its **meta-object protocol (MOP)**: the runtime layer that looks up methods, properties, and operators by name on a per-call basis instead of binding them at compile time. Every untyped (`def`) parameter, untyped closure, dynamic property access, and non-`@CompileStatic` class goes through the MOP.

`@CompileStatic` is a Groovy compiler annotation (in `groovy.transform`) that opts a method or class out of the MOP entirely. With it, the compiler resolves method and property calls at compile time, emits direct JVM bytecode (`invokevirtual`, `invokestatic`, `invokeinterface`) to your real targets, and rejects code it cannot resolve statically. The result is bytecode equivalent to what you'd get from Java, with no runtime dispatch overhead.

This guide explains what to look for in a profile, why it happens, and the highest-leverage source-level change you can make.

## Why dynamic dispatch costs more on aarch64

A dynamic Groovy method call (the default for any `def`-typed parameter, untyped closure, MOP-driven property access, or non-`@CompileStatic` class) goes through a chain that looks roughly like:

```
your call → CallSite → MetaClassImpl.invokeMethod →
  ClosureMetaClass.invokeMethod → CachedMethod.invoke →
  java.lang.reflect.Method.invoke → your method
```

That chain is mostly indirect calls and `MethodHandle` chains. Two things make it more expensive on aarch64:

1. **Indirect-branch codegen.** Both x86_64 and aarch64 cores predict indirect branches well in steady state, but the per-call overhead in code that's heavily MethodHandle-based can be higher in absolute cycles on aarch64, especially for cold or polymorphic call sites.
2. **`MethodHandle` lambda forms.** When a single hot frame fans out to thousands of distinct LambdaForm specializations (which Groovy's meta-object-protocol does), the working set grows and code-cache pressure rises. Microarchitectural differences in how Graviton handles that pressure (instruction cache, ITLB, and JIT code-cache eviction behavior) tend to show up as a measurable per-call delta versus equivalent x86 cores.

The net effect: a Groovy app spending a majority of its CPU in metaobject-protocol frames will see a noticeably larger per-call cost on Graviton than on x86. One fix is to simply remove the dispatch overhead. 

## How to identify

Capture an on-CPU flame graph using [async-profiler](https://github.com/async-profiler/async-profiler) under representative load:

```sh
asprof -e cpu -d 60 -f profile.html <pid>
```

Open the HTML and search for these frames. If their combined inclusive time is more than ~20% of total CPU, dynamic dispatch is your hot path:

| Frame | What it indicates |
|---|---|
| `groovy.lang.MetaClassImpl.invokeMethod` | dynamic method dispatch through the MOP |
| `org.codehaus.groovy.runtime.metaclass.ClosureMetaClass.invokeMethod` | closure call through the MOP |
| `org.codehaus.groovy.reflection.CachedMethod.invoke` | reflective call from MOP into your method |
| `java.lang.reflect.Method.invoke` (with Groovy frames as parents) | reflective dispatch, expensive everywhere, more so on aarch64 |
| `org.codehaus.groovy.runtime.callsite.CallSiteArray.defaultCall` | first-call slow path; high % means many cold call sites |
| `org.codehaus.groovy.runtime.GStringImpl.<init>` / `.toString` | `"foo ${bar}"` interpolation, small but adds up |

On Groovy 3.0+ with `invokedynamic` enabled (the default on Groovy 4+), the MOP still drives dispatch but it is reached through the JVM's `invokedynamic` machinery. You'll see additional frames riding alongside the ones above:

| Frame | What it indicates |
|---|---|
| `java.lang.invoke.Invokers$Holder.linkToCallSite` | `invokedynamic` call-site resolution |
| `java.lang.invoke.LambdaForm$MH.*` (`guard`, `invoke`, `guardWithCatch`, etc.) | MethodHandle / LambdaForm trampolines used by `invokedynamic` |
| `java.lang.invoke.DelegatingMethodHandle$Holder.delegate` | MethodHandle delegation chain |
| `org.codehaus.groovy.vmplugin.v8.IndyInterface.*` (`bootstrap`, `selectMethod`) | Groovy's `invokedynamic` bootstrap into the MOP |

You may also see `org.codehaus.groovy.runtime.ConvertedClosure.invokeCustom` if a `Closure` is being adapted to a SAM type via reflection (e.g., a Groovy closure passed to a Java API that takes a `Predicate` or `Function`). Plain `findAll {...}` / `any {...}` calls into `DefaultGroovyMethods` do not produce this frame, so its absence in your profile doesn't mean the MOP isn't busy.

A useful comparison: capture a profile on an x86 instance and on a Graviton instance at the same load. If the Groovy MOP frames above are noticeably hotter on Graviton, that's the same pattern this guide addresses.

A profile dominated by `Method.invoke` and `MetaClassImpl.invokeMethod` is a strong signal that `@CompileStatic` will give a meaningful speedup. A profile dominated by Jackson, JDBC, Netty, or your own Java code is not. Groovy isn't the bottleneck and `@CompileStatic` won't help.

## example: a coupon eligibility engine

Imagine a checkout service that decides which promotional coupons apply to a cart. The rule layer is in Groovy:

```groovy
// CouponEligibility.groovy: all dynamic
package com.example.coupons

class CouponEligibility {

    static def eligibleCoupons(def cart, def user, def coupons) {
        return coupons.findAll { coupon ->
            applies(cart, user, coupon)
        }
    }

    static def applies(def cart, def user, def coupon) {
        if (!coupon.active) return false
        if (coupon.minSubtotal && cart.subtotal < coupon.minSubtotal) return false
        if (coupon.requiresMembership && !user.isMember) return false
        if (coupon.excludedCategories) {
            def excluded = coupon.excludedCategories
            def hit = cart.items.any { item -> excluded.contains(item.category) }
            if (hit) return false
        }
        if (coupon.region && coupon.region != user.region) return false
        return true
    }

    static def discount(def cart, def coupon) {
        if (coupon.flatAmount) return coupon.flatAmount
        if (coupon.percent) return cart.subtotal * (coupon.percent / 100.0)
        return 0
    }
}
```

Under load (Groovy 4.0.24), a profile shows roughly the following inclusive-time pattern (a frame's percentage is the share of samples whose stack contains it, so MOP frames stack up near 100% because almost every sample passes through them; on Groovy 4 you'll also see `linkToCallSite` and `LambdaForm$MH.*` frames at similar percentages, omitted here for readability):

```
% (inclusive)
~99%  com.example.coupons.CouponEligibility.eligibleCoupons
~99%  org.codehaus.groovy.runtime.DefaultGroovyMethods.findAll
~99%  groovy.lang.MetaClassImpl.invokeMethod
~95%  org.codehaus.groovy.runtime.metaclass.ClosureMetaClass.invokeMethod
~90%  org.codehaus.groovy.reflection.CachedMethod.invoke
~90%  java.lang.reflect.Method.invoke
~60%  com.example.coupons.CouponEligibility.applies
```

Almost nothing is in your code. The work is dispatch.

### The fix

Add `@CompileStatic` and declare types. The control flow is unchanged:

```groovy
// CouponEligibility.groovy: @CompileStatic
package com.example.coupons

import groovy.transform.CompileStatic

@CompileStatic
class CouponEligibility {

    static List<Coupon> eligibleCoupons(Cart cart, User user, List<Coupon> coupons) {
        List<Coupon> out = new ArrayList<>(coupons.size())
        for (Coupon c in coupons) {
            if (applies(cart, user, c)) out.add(c)
        }
        return out
    }

    static boolean applies(Cart cart, User user, Coupon coupon) {
        if (!coupon.active) return false
        if (coupon.minSubtotal != null && cart.subtotal < coupon.minSubtotal) return false
        if (coupon.requiresMembership && !user.member) return false
        if (coupon.excludedCategories != null) {
            Set<String> excluded = coupon.excludedCategories
            for (CartItem item in cart.items) {
                if (excluded.contains(item.category)) return false
            }
        }
        if (coupon.region != null && coupon.region != user.region) return false
        return true
    }

    static BigDecimal discount(Cart cart, Coupon coupon) {
        if (coupon.flatAmount != null) return coupon.flatAmount
        if (coupon.percent != null) return cart.subtotal * (coupon.percent / 100.0G)
        return 0G
    }
}
```

Three categories of change:

1. **Method signatures** - replaced `def` with concrete types (`Cart`, `User`, `Coupon`, `List<Coupon>`).
2. **Closure-driven iteration → plain `for`** - `coupons.findAll { ... }` and `cart.items.any { ... }` were rewritten as `for` loops. Under `@CompileStatic` the closure body itself compiles statically and the call to `findAll` resolves directly, but each iteration still pays for closure-call indirection (`Closure.call` / `doCall`) and the closure object's allocation. A `for` loop removes both.
3. **Property access typing** - `coupon.minSubtotal` now resolves to `Coupon.getMinSubtotal()` at compile time (provided `Coupon` has typed fields), instead of a MOP property lookup.

The post-change profile typically looks like:

```
% (inclusive)
~97%  com.example.coupons.CouponEligibility.eligibleCoupons
~65%  com.example.coupons.CouponEligibility.applies
~60%  java.util.HashSet.contains
~10%  java.util.ArrayList.add
  -   groovy.lang.MetaClassImpl.invokeMethod   (gone)
  -   org.codehaus.groovy.runtime.metaclass.ClosureMetaClass.invokeMethod   (gone)
  -   org.codehaus.groovy.reflection.CachedMethod.invoke   (gone)
  -   java.lang.reflect.Method.invoke   (gone, except in unrelated code)
```

The work is now in your code and not in the dispatch layers. 

## Where to apply `@CompileStatic`

Three scopes, in increasing aggressiveness:

```groovy
// per-method: surgical
class Foo {
    @CompileStatic
    static int hot(...) { ... }
    static def cold(def x) { ... }
}

// per-class: usual choice
@CompileStatic
class Foo { ... }

// per-package: put in package-info.groovy
@groovy.transform.CompileStatic
package com.example.coupons
```

Within a `@CompileStatic` class, you can opt one method back out with `@CompileStatic(TypeCheckingMode.SKIP)` when it genuinely needs the MOP.

## What `@CompileStatic` does not fix

- **`DefaultGroovyMethods` closures.** `.any`, `.findAll`, `.collect`, `.each` still go through `ClosureMetaClass.invokeMethod` even with `@CompileStatic` and a typed closure parameter. Replace them with `for` loops in hot paths.
- **Calls into other dynamic Groovy code.** If `A` is `@CompileStatic` but calls `B.foo()` where `B` is not, the call from `A` to `B.foo()` is still dynamic. Migrate bottom-up from leaf utilities.
- **Runtime-evaluated code.** `GroovyShell`, `Eval.me`, GString templates compiled at runtime, and dynamic code generation are not statically compilable.
- **Genuinely dynamic property/method names.** `obj."${variable}"`, `obj.invokeMethod(name, args)`, and similar cannot be resolved at compile time.

## Verification

After applying `@CompileStatic`, confirm the bytecode is actually static:

```sh
javap -p -c build/classes/groovy/main/com/example/coupons/CouponEligibility.class \
    | grep -E 'invoke(virtual|static|interface|dynamic)'
```

You want to see `invokevirtual` / `invokestatic` calls to your real method targets. If you see `invokedynamic` instructions whose descriptor is `:invoke:` or `:getProperty:` against your own methods (instead of `invokevirtual`/`invokestatic` to the real target), dispatch is still dynamic. Usually this is because a parameter remained `def` or a closure parameter is untyped.

Note: even fully static code can contain `invokedynamic` whose descriptor is `:cast:`. That's Groovy's typed cast operator (e.g. casting an `Object` returned from generic code back to your concrete type), not method dispatch. Ignore it.

Re-run the on-CPU profile under the same load. The MOP frames listed in the *How to identify* section should drop dramatically. If `MetaClassImpl.invokeMethod` is still present at meaningful percentages, search for which call site is producing it (the parent frame in the flame graph).

## A note on `@TypeChecked`

`@TypeChecked` performs static type checking but **still emits dynamic dispatch bytecode.** It catches type errors at compile time but provides no runtime speedup. Use `@CompileStatic` for performance.

## Migration strategy

For an existing codebase with a lot of dynamic Groovy:

1. **Profile first.** Don't `@CompileStatic` what isn't hot. Pick the top 5 frames by inclusive time and migrate the classes that contain them.
2. **Migrate leaves first.** Pure helper classes (utility methods, dispatch glue, rule evaluators) convert easily because they don't subclass other dynamic Groovy.
3. **Add `@CompileStatic` at class scope, fix the compile errors.** The errors are precise. They tell you the exact line where dynamic dispatch was load-bearing.
4. **Don't refactor logic during the conversion.** Keep behavior byte-for-byte identical so the perf delta is attributable.
5. **Re-profile after each migrated class.** Confirms you cut the targeted frames and didn't shift cost elsewhere.
6. **Leave user-facing DSLs dynamic if they're not hot.** Domain DSLs are often 5–10% of code but provide most of Groovy's value; readability for non-engineers is usually worth more than the perf delta on cold rules. Compile the dispatcher / engine underneath them statically; leave the rule files dynamic.

## Other Groovy tuning that helps on Graviton

`@CompileStatic` is the highest-leverage change. A few smaller knobs that may also add value:

- **Use the invokedynamic build of Groovy** if you must stay on dynamic Groovy. On Groovy 4.0+ this is already the default: there is a single set of jars, compiled with `invokedynamic`, and no flag is needed. On Groovy 2.x/3.x it requires (a) the `-indy` classifier jar and (b) compiling with the indy flag (`groovy --indy`, or `groovy.target.indy=true` for the compiler); there is no runtime system property that toggles it. The profile signature shifts from `CachedMethod.invoke` / `Method.invoke` to frames like `IndyInterface.bootstrap` / `IndyInterface.selectMethod` and generated `LambdaForm$MH` frames. It's somewhat cheaper but still much more expensive than static dispatch.
- **Adjust `-XX:ReservedCodeCacheSize`** if `jcmd <pid> Compiler.codecache` shows the code cache near full. Groovy generates many specialized LambdaForms; a full code cache causes JIT'd code to be flushed and recompiled, which on Graviton can manifest as periodic latency spikes.
- **Avoid GString in hot paths.** `"foo ${bar}"` allocates a `GStringImpl` and calls `.toString()` on demand. In a tight loop, plain string concatenation or `String.format` is cheaper. The profile signature is `GStringImpl.<init>`.
- **Avoid `as Type` coercions in hot paths.** They route through `DefaultGroovyMethods.asType`. Use the direct API (`Integer.parseInt(s)`, `(String) o`, etc.) when you know the source type.

## Summary

If your Groovy app shows a Graviton-vs-x86 per-thread regression, capture a flame graph and look for `MetaClassImpl.invokeMethod`, `CachedMethod.invoke`, `Method.invoke`, and `linkToCallSite` in your hot path. If they sum to an appreciable portion of CPU, applying `@CompileStatic` to the classes that drive them (and replacing closure calls with `for` loops in those classes) typically recovers a large fraction of the gap, and for dispatch-bound workloads can close it entirely or exceed the original x86 baseline.
