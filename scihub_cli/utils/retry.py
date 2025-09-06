"""
Retry mechanism utilities for Sci-Hub CLI.
"""

import time
from typing import Callable, Any, Optional
from functools import wraps
from ..utils.logging import get_logger

logger = get_logger(__name__)

class RetryConfig:
    """Configuration for retry behavior."""
    
    def __init__(self, 
                 max_attempts: int = 3,
                 base_delay: float = 2.0,
                 backoff_multiplier: float = 2.0,
                 max_delay: float = 60.0):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.backoff_multiplier = backoff_multiplier
        self.max_delay = max_delay

def with_retry(retry_config: RetryConfig, 
               exceptions: tuple = (Exception,),
               logger_name: Optional[str] = None):
    """Decorator for adding retry logic to functions."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            retry_logger = get_logger(logger_name) if logger_name else logger
            
            for attempt in range(retry_config.max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < retry_config.max_attempts - 1:
                        # Calculate delay with exponential backoff
                        delay = min(
                            retry_config.base_delay * (retry_config.backoff_multiplier ** attempt),
                            retry_config.max_delay
                        )
                        retry_logger.warning(
                            f"Attempt {attempt + 1}/{retry_config.max_attempts} failed: {e}. "
                            f"Retrying in {delay:.1f} seconds..."
                        )
                        time.sleep(delay)
                    else:
                        retry_logger.error(
                            f"All {retry_config.max_attempts} attempts failed. Last error: {e}"
                        )
            
            raise last_exception
        return wrapper
    return decorator

def retry_operation(operation: Callable,
                   retry_config: RetryConfig,
                   operation_name: str = "operation",
                   *args, **kwargs) -> Any:
    """Retry an operation with the given configuration."""
    last_exception = None
    
    for attempt in range(retry_config.max_attempts):
        try:
            return operation(*args, **kwargs)
        except Exception as e:
            last_exception = e
            if attempt < retry_config.max_attempts - 1:
                delay = min(
                    retry_config.base_delay * (retry_config.backoff_multiplier ** attempt),
                    retry_config.max_delay
                )
                logger.info(f"{operation_name} failed (attempt {attempt + 1}), retrying in {delay:.1f}s...")
                time.sleep(delay)
    
    logger.error(f"{operation_name} failed after {retry_config.max_attempts} attempts")
    raise last_exception