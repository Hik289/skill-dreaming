from pathlib import Path
import sys
import docker
import experiment as driver
from verified_infrastructure_v2 import normalize_checkout
original_from_env = docker.from_env

def docker_from_env(*args, **kwargs):
    kwargs.setdefault('timeout', 240)
    return original_from_env(*args, **kwargs)
docker.from_env = docker_from_env
driver.normalize_checkout = normalize_checkout
driver.__file__ = __file__
if __name__ == '__main__':
    run = Path(sys.argv[sys.argv.index('--run') + 1])
    if run.parent.name != 'verified':
        raise RuntimeError('This recovery driver is Verified-only')
    driver.main()
