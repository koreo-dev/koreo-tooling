"""Koreo tooling package initialization"""

import pathlib
import logging

logger = logging.getLogger("koreo.tooling")


def get_crd_path():
    """Get the path to CRD files from the koreo-core package"""
    try:
        # Use the same CRD_ROOT as the core package
        from koreo.schema import CRD_ROOT
        if CRD_ROOT.exists():
            logger.debug(f"Using CRDs from koreo-core package at {CRD_ROOT}")
            return CRD_ROOT
    except ImportError:
        logger.warning("koreo-core package not installed, falling back to local CRDs")
    
    # Fallback to local CRDs for development
    current_dir = pathlib.Path(__file__).parent
    
    # Try relative to tooling project root
    dev_crd = current_dir.parent.parent / "crd"
    if dev_crd.exists():
        logger.debug(f"Using local CRDs for development at {dev_crd}")
        return dev_crd
    
    # Try relative to core project
    core_crd = current_dir.parent.parent.parent.parent / "core" / "crd"
    if core_crd.exists():
        logger.debug(f"Using CRDs from sibling core project at {core_crd}")
        return core_crd
    
    # Final fallback
    logger.warning(f"CRD files not found, using fallback path: {dev_crd}")
    return dev_crd


def load_schema_validators():
    """Load schema validators using koreo-core's schema loading infrastructure"""
    try:
        # Import and use koreo-core's schema loading function directly
        # This will use the core package's CRD_ROOT automatically, or our fallback
        from koreo.schema import load_validators_from_files
        crd_path = get_crd_path()
        load_validators_from_files(clear_existing=True, path=crd_path)
        
        logger.info(f"Schema validators loaded from {crd_path}")
    except ImportError as e:
        logger.error(f"Failed to import koreo-core schema module: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to load schema validators: {e}")
        raise