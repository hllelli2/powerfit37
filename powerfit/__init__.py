import sys, os
env_path = sys.prefix

if sys.version_info > (3, 8):
    site_packages_path = os.path.join(env_path, 'lib', f'python{sys.version_info.major}.{sys.version_info.minor}', 'site-packages')
else:
    site_packages_path = os.path.join(env_path, 'lib', 'python3.8', 'site-packages')


sys.path.insert(0, site_packages_path)
from .volume_helpers import structure_to_shape_like
from .structure_helpers import Structure
from .rotations import proportional_orientations, quat_to_rotmat
from .helpers import determine_core_indices
