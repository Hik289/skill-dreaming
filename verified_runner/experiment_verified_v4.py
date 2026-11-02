from pathlib import Path
import sys
from experiment_verified_v3 import driver
from verified_infrastructure_v3 import normalize_checkout
driver.normalize_checkout = normalize_checkout
driver.__file__ = __file__
if __name__ == '__main__':
    run = Path(sys.argv[sys.argv.index('--run') + 1])
    if run.parent.name != 'verified':
        raise RuntimeError('This recovery driver is Verified-only')
    driver.main()
