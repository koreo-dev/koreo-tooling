"""Koreo tooling package for language server and CLI tools"""

import pathlib


def get_crd_path():
    """Get the path to CRD files, handling both development and installed modes"""
    # Development mode - CRD files at repo root
    dev_crd = pathlib.Path(__file__).parent.parent.parent / "crd"
    if dev_crd.exists():
        return dev_crd
    
    # Check if CRD files were installed alongside the package
    package_crd = pathlib.Path(__file__).parent / "crd"
    if package_crd.exists():
        return package_crd
    
    # Try to find in parent directories
    current = pathlib.Path(__file__).parent
    for _ in range(3):
        test_crd = current / "crd"
        if test_crd.exists():
            return test_crd
        current = current.parent
    
    # Last resort - assume development structure
    return dev_crd


# Export the CRD path for use by other modules
CRD_PATH = get_crd_path()