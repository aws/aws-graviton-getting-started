import json
import math
import platform
import timeit
def primes_up_to(n):
    primes = []
    for i in range(2, n+1):
        is_prime = True
        sqrt_i = math.isqrt(i)
        for p in primes:
            if p > sqrt_i:
                break
            if i % p == 0:
                is_prime = False
                break
        if is_prime:
            primes.append(i)
    return primes

def lambda_handler(event, context):
    print(event)
    start_time = timeit.default_timer()
    N = int(event['queryStringParameters']['max'])
    primes = primes_up_to(N)
    stop_time = timeit.default_timer()
    elapsed_time = stop_time - start_time

    response = {
        'machine': platform.machine(),
        'elapsed': elapsed_time,
        'message': 'There are {} prime numbers <= {}'.format(len(primes), N)
    }
    
    return {
        'statusCode': 200,
        'body': json.dumps(response)
    }