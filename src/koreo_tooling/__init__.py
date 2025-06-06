"""Koreo tooling package for language server and CLI tools"""

import pathlib


def get_crd_path():
    """Get the path to CRD files, handling both development and installed modes"""
    # Development mode - CRD files at repo root
    dev_crd = pathlib.Path(__file__).parent.parent.parent / "crd"
    if dev_crd.exists():
        return dev_crd
    
    # Installed mode - CRD files packaged with the module
    package_crd = pathlib.Path(__file__).parent / "crd"
    if package_crd.exists():
        return package_crd
    
    # Fallback - assume development structure
    return dev_crd


def load_schema_validators():
    """Load schema validators, using appropriate path for the environment"""
    from koreo import schema
    
    crd_path = get_crd_path()
    # Always use our CRD files since koreo-core doesn't package them
    schema.load_validators_from_files(path=crd_path)


# Export the CRD path for use by other modules (may be None for installed packages)
CRD_PATH = get_crd_path()