#!/usr/bin/env bash
#
# Launch one x86-64 and one Graviton instance in your AWS account, build and
# run pricer.cpp on both (default and -ffp-contract=off builds), bring the
# results back, compare them, and terminate everything.
#
# Requirements on your machine: AWS CLI v2 with credentials, python3.
# Nothing is installed locally. Instances are reached with SSM Run Command,
# so no SSH key and no inbound security group rule are created.
#
# Every resource created by a run carries a unique run id, so concurrent runs
# are isolated and cleaning up one run never touches another.
#
# Usage:
#   ./run-aws.sh [--region R] [--x86 TYPE] [--arm TYPE] [--bench]
#                [--instance-profile NAME] [--keep]
#   ./run-aws.sh --cleanup-only [--run-id ID] [--region R]
#
# AWS credentials come from the environment as usual (AWS_PROFILE, env vars,
# or the default profile).
#
#   --region        AWS region (default us-east-1)
#   --x86           x86-64 instance type (default c8a.xlarge, AMD)
#   --arm           arm64 instance type  (default c9g.xlarge, Graviton5)
#   --bench         also run bench.cpp on both hosts and report throughput,
#                   cores, and best-effort On-Demand and Spot prices
#   --instance-profile NAME
#                   use an existing IAM instance profile that allows SSM and
#                   s3:PutObject to the results bucket, instead of creating one
#   --keep          leave instances running afterwards. The run prints its
#                   run id and the --cleanup-only command to remove them later
#   --run-id ID     reuse a specific run id, for cleaning up one earlier run
#   --cleanup-only  remove resources and exit. With --run-id, removes only that
#                   run. Without it, removes every run's resources in the
#                   region and account (asked for explicitly)
#
# Permissions needed by the caller: ec2 (run/describe/terminate instances,
# security groups), ssm (send-command, get-command-invocation), s3 (create,
# put, get, delete a bucket), and iam (create/delete role and instance
# profile) unless --instance-profile is given. A ready-made policy is in
# README.md.
#
# Cost: two instances for roughly ten minutes.

set -euo pipefail

REGION="us-east-1"
X86_TYPE="c8a.xlarge"
ARM_TYPE="c9g.xlarge"
PROFILE_NAME=""
BENCH=0
KEEP=0
CLEANUP_ONLY=0
RUN_ID=""

while [ $# -gt 0 ]; do
    case "$1" in
        --region)  REGION="$2"; shift 2;;
        --x86)     X86_TYPE="$2"; shift 2;;
        --arm)     ARM_TYPE="$2"; shift 2;;
        --bench)   BENCH=1; shift;;
        --instance-profile) PROFILE_NAME="$2"; shift 2;;
        --keep)    KEEP=1; shift;;
        --cleanup-only) CLEANUP_ONLY=1; shift;;
        --run-id)  RUN_ID="$2"; shift 2;;
        -h|--help) awk 'NR>1 && /^#/{sub(/^# ?/,""); print; next} NR>1{exit}' "$0"; exit 0;;
        *) echo "unknown option: $1" >&2; exit 2;;
    esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TAG="graviton-numerical-validation"
BUCKET_PREFIX="gnv-results-"

# Every resource this script creates carries a unique run id, so that
# concurrent runs, and cleanup of an interrupted run, never touch another
# run's instances, bucket, security group or IAM role. --cleanup-only with no
# --run-id is the one exception: it sweeps every run's resources in the
# account, which is why it has to be asked for explicitly.
SWEEP_ALL=0
if [ "$CLEANUP_ONLY" = 1 ] && [ -z "$RUN_ID" ]; then
    SWEEP_ALL=1
fi
[ -n "$RUN_ID" ] || RUN_ID="$(date +%Y%m%d-%H%M%S)-$RANDOM"

OUT_DIR="$HERE/results/run-$RUN_ID"
SG_NAME="$TAG-$RUN_ID-sg"
ROLE_NAME="$TAG-$RUN_ID"
OWN_PROFILE=0
BUCKET=""
INSTANCE_IDS=()
SG_ID=""

aws_() { aws --region "$REGION" --output text "$@"; }
log()  { printf '>> %s\n' "$*"; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- cleanup ---

# Remove the IAM role and instance profile with the given name.
delete_role() {
    local role="$1"
    aws_ iam remove-role-from-instance-profile --instance-profile-name "$role" --role-name "$role" >/dev/null 2>&1
    aws_ iam delete-instance-profile --instance-profile-name "$role" >/dev/null 2>&1
    aws_ iam detach-role-policy --role-name "$role" --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore >/dev/null 2>&1
    aws_ iam delete-role-policy --role-name "$role" --policy-name results-bucket >/dev/null 2>&1
    aws_ iam delete-role --role-name "$role" >/dev/null 2>&1 && log "Deleted IAM role $role"
}

cleanup() {
    set +e
    if [ "$KEEP" = 1 ] && [ "$CLEANUP_ONLY" = 0 ]; then
        log "--keep given, leaving instances running: ${INSTANCE_IDS[*]:-none}"
        log "Run '$0 --region $REGION --cleanup-only --run-id $RUN_ID' to remove this run later."
        return
    fi

    # Instances: scope to this run by RunId tag, unless sweeping all runs.
    local inst_filter ids
    if [ "$SWEEP_ALL" = 1 ]; then
        log "Cleaning up ALL $TAG runs in $REGION"
        inst_filter="Name=tag:Project,Values=$TAG"
    else
        log "Cleaning up run $RUN_ID"
        inst_filter="Name=tag:RunId,Values=$RUN_ID"
    fi
    ids=$(aws_ ec2 describe-instances \
        --filters "$inst_filter" \
                  "Name=instance-state-name,Values=pending,running,stopping,stopped" \
        --query 'Reservations[].Instances[].InstanceId')
    if [ -n "$ids" ]; then
        log "Terminating $ids"
        aws_ ec2 terminate-instances --instance-ids $ids >/dev/null
        aws_ ec2 wait instance-terminated --instance-ids $ids
    fi

    # Security groups, buckets and roles: this run's by name, or every run's
    # when sweeping. A security group cannot be deleted until the instances
    # that used it are gone, so this retries.
    local sgs roles buckets
    if [ "$SWEEP_ALL" = 1 ]; then
        sgs=$(aws_ ec2 describe-security-groups \
            --filters "Name=group-name,Values=$TAG-*-sg" --query 'SecurityGroups[].GroupName')
        roles=$(aws_ iam list-roles --query "Roles[?starts_with(RoleName, '$TAG-')].RoleName")
        buckets=$(aws_ s3api list-buckets --query "Buckets[?starts_with(Name, '$BUCKET_PREFIX')].Name")
    else
        sgs="$SG_NAME"
        buckets="$BUCKET"
        if [ "$OWN_PROFILE" = 1 ] || [ "$CLEANUP_ONLY" = 1 ]; then
            roles="$ROLE_NAME"
        else
            roles=""
        fi
    fi

    for sg in $sgs; do
        for _ in 1 2 3 4 5 6; do
            aws_ ec2 delete-security-group --group-name "$sg" >/dev/null 2>&1 && { log "Deleted security group $sg"; break; }
            sleep 10
        done
    done
    for b in $buckets; do
        [ -n "$b" ] || continue
        aws_ s3 rb "s3://$b" --force >/dev/null 2>&1 && log "Deleted bucket $b"
    done
    for r in $roles; do
        [ -n "$r" ] || continue
        delete_role "$r"
    done
    log "Cleanup complete"
}
trap cleanup EXIT

if [ "$CLEANUP_ONLY" = 1 ]; then exit 0; fi

# ------------------------------------------------------------- preflight ---

command -v aws >/dev/null || die "aws CLI not found"
command -v python3 >/dev/null || die "python3 not found"
[ -f "$HERE/pricer.cpp" ] || die "pricer.cpp not found next to this script"

ACCOUNT=$(aws_ sts get-caller-identity --query Account) || die "AWS credentials not available"
log "Account $ACCOUNT, region $REGION"

offered=$(aws_ ec2 describe-instance-type-offerings --location-type region \
    --filters "Name=instance-type,Values=$X86_TYPE,$ARM_TYPE" \
    --query 'InstanceTypeOfferings[].InstanceType')
for t in "$X86_TYPE" "$ARM_TYPE"; do
    grep -qw "$t" <<<"$offered" || die "$t is not offered in $REGION. Try --region us-east-2, us-west-2 or eu-central-1."
done

ami_for() {
    aws_ ec2 describe-images --owners amazon \
        --filters "Name=name,Values=al2023-ami-2023.*-kernel-*-$1" "Name=state,Values=available" \
        --query 'reverse(sort_by(Images,&CreationDate))[:1].ImageId'
}
AMI_X86=$(ami_for x86_64); AMI_ARM=$(ami_for arm64)
[ -n "$AMI_X86" ] && [ -n "$AMI_ARM" ] || die "could not resolve AL2023 AMIs in $REGION"
log "AMIs: x86_64 $AMI_X86, arm64 $AMI_ARM"

# ---------------------------------------------------------------- bucket ---

BUCKET="$BUCKET_PREFIX$ACCOUNT-$RUN_ID"
if [ "$REGION" = "us-east-1" ]; then
    aws_ s3api create-bucket --bucket "$BUCKET" >/dev/null
else
    aws_ s3api create-bucket --bucket "$BUCKET" \
        --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
fi
aws_ s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
log "Results bucket $BUCKET"

# ------------------------------------------------------------------- IAM ---

if [ -z "$PROFILE_NAME" ]; then
    PROFILE_NAME="$ROLE_NAME"
    OWN_PROFILE=1
    if ! aws_ iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
        log "Creating IAM role $ROLE_NAME (SSM core + put to results bucket)"
        aws_ iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document \
            '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
        aws_ iam attach-role-policy --role-name "$ROLE_NAME" \
            --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
    fi
    aws_ iam put-role-policy --role-name "$ROLE_NAME" --policy-name results-bucket --policy-document \
        "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"s3:PutObject\",\"Resource\":\"arn:aws:s3:::$BUCKET/*\"}]}"
    if ! aws_ iam get-instance-profile --instance-profile-name "$ROLE_NAME" >/dev/null 2>&1; then
        aws_ iam create-instance-profile --instance-profile-name "$ROLE_NAME" >/dev/null
        aws_ iam add-role-to-instance-profile --instance-profile-name "$ROLE_NAME" --role-name "$ROLE_NAME"
        log "Waiting for instance profile to propagate"; sleep 15
    fi
fi

# --------------------------------------------------------- security group ---

SG_ID=$(aws_ ec2 describe-security-groups --group-names "$SG_NAME" \
    --query 'SecurityGroups[0].GroupId' 2>/dev/null || true)
if [ -z "$SG_ID" ] || [ "$SG_ID" = "None" ]; then
    SG_ID=$(aws_ ec2 create-security-group --group-name "$SG_NAME" \
        --description "$TAG run $RUN_ID (no inbound rules, SSM only)" \
        --tag-specifications "ResourceType=security-group,Tags=[{Key=Project,Value=$TAG},{Key=RunId,Value=$RUN_ID}]" \
        --query GroupId)
fi

# ---------------------------------------------------------------- launch ---

launch() {
    local label="$1" itype="$2" ami="$3" iid
    for attempt in 1 2 3 4 5; do
        iid=$(aws_ ec2 run-instances --image-id "$ami" --instance-type "$itype" \
            --iam-instance-profile "Name=$PROFILE_NAME" --security-group-ids "$SG_ID" \
            --metadata-options "HttpTokens=required,HttpEndpoint=enabled,HttpPutResponseHopLimit=1" \
            --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"Encrypted":true,"DeleteOnTermination":true}}]' \
            --tag-specifications "ResourceType=instance,Tags=[{Key=Project,Value=$TAG},{Key=RunId,Value=$RUN_ID},{Key=Name,Value=$TAG-$RUN_ID-$label}]" \
            --query 'Instances[0].InstanceId' 2>/tmp/launch.err) && { echo "$iid"; return; }
        sleep 8
    done
    die "failed to launch $label ($itype): $(head -1 /tmp/launch.err)"
}
log "Launching $X86_TYPE (x86_64) and $ARM_TYPE (arm64)"
IID_X86=$(launch x86 "$X86_TYPE" "$AMI_X86")
IID_ARM=$(launch arm "$ARM_TYPE" "$AMI_ARM")
INSTANCE_IDS=("$IID_X86" "$IID_ARM")
aws_ ec2 wait instance-running --instance-ids "${INSTANCE_IDS[@]}"

log "Waiting for SSM agents to register"
for iid in "${INSTANCE_IDS[@]}"; do
    for _ in $(seq 1 40); do
        st=$(aws_ ssm describe-instance-information \
            --filters "Key=InstanceIds,Values=$iid" --query 'InstanceInformationList[0].PingStatus' 2>/dev/null || true)
        [ "$st" = "Online" ] && break
        sleep 5
    done
    [ "$st" = "Online" ] || die "$iid did not register with SSM"
done

# ------------------------------------------------------------------- run ---

# Everything the instance needs is embedded in the command so no file copy
# step is required. The source is base64-encoded to survive the JSON
# parameter quoting.
SRC_B64=$(base64 < "$HERE/pricer.cpp" | tr -d '\n')
BENCH_B64=""
[ "$BENCH" = 1 ] && BENCH_B64=$(base64 < "$HERE/bench.cpp" | tr -d '\n')

REMOTE_SCRIPT=$(cat <<'EOF'
set -e
dnf install -y -q gcc-c++ >/dev/null 2>&1
mkdir -p /tmp/pv && cd /tmp/pv
echo "$SRC_B64" | base64 -d > pricer.cpp
F="-std=c++17 -O3 -pthread"
g++ $F                   -DBUILD_FLAGS="\"$F\""                   pricer.cpp -o pricer
g++ $F -ffp-contract=off -DBUILD_FLAGS="\"$F -ffp-contract=off\"" pricer.cpp -o pricer-strict
echo "### host"
echo "gcc   : $(g++ --version | head -1)"
echo "glibc : $(ldd --version | head -1)"
echo "### pricer (compiler default contraction)"
./pricer        --dump default.bin
echo "### pricer-strict (-ffp-contract=off)"
./pricer-strict --dump strict.bin --threads 0
echo "### uploading dumps"
aws s3 cp --quiet default.bin "s3://$BUCKET/$LABEL/default.bin"
aws s3 cp --quiet strict.bin  "s3://$BUCKET/$LABEL/strict.bin"
if [ -n "$BENCH_B64" ]; then
  echo "$BENCH_B64" | base64 -d > bench.cpp
  g++ $F bench.cpp -o bench
  echo "### bench (all hardware threads, best of 8)"
  ./bench
fi
echo "done"
EOF
)

run_remote() {
    local label="$1" iid="$2" cid status
    local cmd="export SRC_B64='$SRC_B64' BENCH_B64='$BENCH_B64' BUCKET='$BUCKET' LABEL='$label'; $REMOTE_SCRIPT"
    cid=$(aws_ ssm send-command --instance-ids "$iid" --document-name AWS-RunShellScript \
        --timeout-seconds 900 \
        --parameters "$(python3 -c 'import json,sys; print(json.dumps({"commands":[sys.stdin.read()],"executionTimeout":["900"]}))' <<<"$cmd")" \
        --query 'Command.CommandId')
    for _ in $(seq 1 180); do
        status=$(aws_ ssm get-command-invocation --command-id "$cid" --instance-id "$iid" --query Status 2>/dev/null || echo Pending)
        case "$status" in Success|Failed|Cancelled|TimedOut) break;; esac
        sleep 5
    done
    aws_ ssm get-command-invocation --command-id "$cid" --instance-id "$iid" --query StandardOutputContent > "$OUT_DIR/$label.txt"
    if [ "$status" != "Success" ]; then
        aws_ ssm get-command-invocation --command-id "$cid" --instance-id "$iid" --query StandardErrorContent >&2
        die "remote run on $label ($iid) ended with status $status"
    fi
}

mkdir -p "$OUT_DIR"
log "Building and running on both hosts (about 2 minutes$([ "$BENCH" = 1 ] && echo ', plus benchmark'))"
run_remote x86 "$IID_X86" & PID_X86=$!
run_remote arm "$IID_ARM" & PID_ARM=$!
wait "$PID_X86" || die "x86 run failed, see above"
wait "$PID_ARM" || die "arm run failed, see above"

log "Downloading price dumps"
aws_ s3 cp --quiet --recursive "s3://$BUCKET/" "$OUT_DIR/"

# --------------------------------------------------------------- report ---

section() { printf '\n==== %s ====\n' "$*"; }

section "x86_64 host ($X86_TYPE)"
cat "$OUT_DIR/x86.txt"
section "arm64 host ($ARM_TYPE)"
cat "$OUT_DIR/arm.txt"

section "Same host, contraction on vs off: x86_64"
python3 "$HERE/compare.py" "$OUT_DIR/x86/default.bin" "$OUT_DIR/x86/strict.bin"
section "Same host, contraction on vs off: arm64"
python3 "$HERE/compare.py" "$OUT_DIR/arm/default.bin" "$OUT_DIR/arm/strict.bin"
section "Across hosts, both -ffp-contract=off: x86_64 vs arm64"
python3 "$HERE/compare.py" "$OUT_DIR/x86/strict.bin" "$OUT_DIR/arm/strict.bin"

{
    section "x86_64 host ($X86_TYPE)"; cat "$OUT_DIR/x86.txt"
    section "arm64 host ($ARM_TYPE)";  cat "$OUT_DIR/arm.txt"
    section "Same host, contraction on vs off: x86_64"
    python3 "$HERE/compare.py" "$OUT_DIR/x86/default.bin" "$OUT_DIR/x86/strict.bin"
    section "Same host, contraction on vs off: arm64"
    python3 "$HERE/compare.py" "$OUT_DIR/arm/default.bin" "$OUT_DIR/arm/strict.bin"
    section "Across hosts, both -ffp-contract=off: x86_64 vs arm64"
    python3 "$HERE/compare.py" "$OUT_DIR/x86/strict.bin" "$OUT_DIR/arm/strict.bin"
} > "$OUT_DIR/report.txt"

# ------------------------------------------------------------ benchmark ---

if [ "$BENCH" = 1 ]; then
    # Pricing API region names for the regions where both default types exist.
    location_for() {
        case "$1" in
            us-east-1)    echo "US East (N. Virginia)";;
            us-east-2)    echo "US East (Ohio)";;
            us-west-2)    echo "US West (Oregon)";;
            eu-central-1) echo "EU (Frankfurt)";;
            eu-west-1)    echo "EU (Ireland)";;
            *)            echo "";;
        esac
    }
    od_price() {  # best effort; the Pricing API lives in us-east-1
        local loc; loc=$(location_for "$REGION"); [ -n "$loc" ] || { echo "n/a"; return; }
        aws --region us-east-1 --output text pricing get-products --service-code AmazonEC2 \
            --filters "Type=TERM_MATCH,Field=instanceType,Value=$1" \
                      "Type=TERM_MATCH,Field=location,Value=$loc" \
                      "Type=TERM_MATCH,Field=operatingSystem,Value=Linux" \
                      "Type=TERM_MATCH,Field=tenancy,Value=Shared" \
                      "Type=TERM_MATCH,Field=preInstalledSw,Value=NA" \
                      "Type=TERM_MATCH,Field=capacitystatus,Value=Used" \
            --query 'PriceList[0]' 2>/dev/null \
        | python3 -c '
import json, sys
try:
    p = json.loads(sys.stdin.read())
    od = p["terms"]["OnDemand"]
    d = next(iter(next(iter(od.values()))["priceDimensions"].values()))
    print("%.4f" % float(d["pricePerUnit"]["USD"]))
except Exception:
    print("n/a")
' 2>/dev/null || echo "n/a"
    }
    spot_price() {  # best effort; most recent Linux/UNIX price in any AZ of the region
        aws_ ec2 describe-spot-price-history --instance-types "$1" \
            --product-descriptions "Linux/UNIX" --start-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
            --query 'sort_by(SpotPriceHistory,&Timestamp)[-1].SpotPrice' 2>/dev/null \
        | awk 'NF && $1!="None"{printf "%.4f\n",$1; f=1} END{if(!f)print "n/a"}' || echo "n/a"
    }
    cores_for() {
        aws_ ec2 describe-instance-types --instance-types "$1" \
            --query 'InstanceTypes[0].VCpuInfo.[DefaultCores,DefaultThreadsPerCore]' 2>/dev/null \
        | tr '\t' 'x' || echo "n/a"
    }
    ops_for()  { awk -F: '/options per sec/{gsub(/ /,"",$2); print $2}' "$OUT_DIR/$1.txt"; }
    util_for() { awk -F: '/cpu utilisation/{gsub(/ /,"",$2); print $2}' "$OUT_DIR/$1.txt"; }
    per_dollar() {
        python3 -c '
import sys
o, p = sys.argv[1], sys.argv[2]
try:
    print("%.3e" % (float(o) / float(p)))
except Exception:
    print("n/a")
' "$1" "$2" 2>/dev/null || echo "n/a"
    }

    bench_table() {
        section "Benchmark: bench.cpp, all hardware threads, best of 8 (see caveats in README)"
        printf '%-8s %-12s %-12s %-6s %-16s %-10s %-10s %-14s %-14s\n' \
            host instance cores_x_smt cpu options_per_sec od_usd_hr spot_usd_hr ops_per_od_usd ops_per_spot_usd
        for pair in "x86:$X86_TYPE" "arm:$ARM_TYPE"; do
            local label="${pair%%:*}" itype="${pair#*:}"
            local ops od sp
            ops=$(ops_for "$label"); od=$(od_price "$itype"); sp=$(spot_price "$itype")
            printf '%-8s %-12s %-12s %-6s %-16s %-10s %-10s %-14s %-14s\n' \
                "$label" "$itype" "$(cores_for "$itype")" "$(util_for "$label")" "$ops" "$od" "$sp" \
                "$(per_dollar "$ops" "$od")" "$(per_dollar "$ops" "$sp")"
        done
        echo
        echo "Prices are point-in-time for $REGION at $(date -u +%Y-%m-%dT%H:%MZ); Spot is the latest price in one AZ."
        echo "One closed-form kernel on one instance size. Not a statement about your workload."
    }
    bench_table
    bench_table >> "$OUT_DIR/report.txt"
fi

log "Report and dumps saved in $OUT_DIR"
