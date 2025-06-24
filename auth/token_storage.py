"""
JSON-based token storage system for secure and reliable token management
"""

import json
import os
import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

logger = logging.getLogger(__name__)

class TokenStorage:
    """JSON-based token storage with encryption"""
    
    def __init__(self, storage_file: str = "auth/tokens.json"):
        self.storage_file = Path(storage_file)
        self.storage_file.parent.mkdir(exist_ok=True)
        
    def _encrypt_token(self, token: str, encryption_key: str) -> str:
        """Encrypt a token using AES-CBC"""
        # Generate random IV
        iv = os.urandom(16)
        
        # Create key from encryption key string using SHA-256
        key_hash = hashlib.sha256(encryption_key.encode()).digest()
        
        # Pad the token to 16-byte boundary (PKCS7 padding)  
        token_bytes = token.encode('utf-8')
        padding_length = 16 - (len(token_bytes) % 16)
        padded_token = token_bytes + bytes([padding_length] * padding_length)
        
        # Encrypt using AES-CBC
        cipher = Cipher(
            algorithms.AES(key_hash),
            modes.CBC(iv),
            backend=default_backend()
        )
        encryptor = cipher.encryptor()
        encrypted = encryptor.update(padded_token) + encryptor.finalize()
        
        # Return IV and encrypted data as hex strings separated by colon
        return f"{iv.hex()}:{encrypted.hex()}"
    
    def _decrypt_token(self, encrypted_token: str, encryption_key: str) -> str:
        """Decrypt a token using AES-CBC"""
        try:
            # Parse the encrypted data format: iv:encrypted
            iv_hex, encrypted_hex = encrypted_token.split(':')
            
            # Convert hex strings to bytes
            iv = bytes.fromhex(iv_hex)
            encrypted = bytes.fromhex(encrypted_hex)
            
            # Create key from encryption key string using SHA-256
            key_hash = hashlib.sha256(encryption_key.encode()).digest()
            
            # Decrypt using AES-CBC
            cipher = Cipher(
                algorithms.AES(key_hash),
                modes.CBC(iv),
                backend=default_backend()
            )
            decryptor = cipher.decryptor()
            decrypted = decryptor.update(encrypted) + decryptor.finalize()
            
            # Remove PKCS7 padding
            padding_length = decrypted[-1]
            return decrypted[:-padding_length].decode('utf-8')
            
        except Exception as e:
            raise ValueError(f"Failed to decrypt token: {str(e)}")
    
    def _load_tokens(self) -> Dict[str, Any]:
        """Load tokens from JSON file"""
        if not self.storage_file.exists():
            logger.info(f"📁 Token file doesn't exist, creating: {self.storage_file}")
            return {}
        
        try:
            with open(self.storage_file, 'r') as f:
                data = json.load(f)
                logger.info(f"📖 Loaded token data from {self.storage_file}")
                return data
        except Exception as e:
            logger.error(f"❌ Failed to load tokens from {self.storage_file}: {e}")
            return {}
    
    def _save_tokens(self, tokens: Dict[str, Any]) -> bool:
        """Save tokens to JSON file"""
        try:
            # Add metadata
            tokens['_metadata'] = {
                'last_updated': datetime.now(timezone.utc).isoformat(),
                'version': '1.0'
            }
            
            # Write to temporary file first, then rename (atomic operation)
            temp_file = self.storage_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(tokens, f, indent=2)
            
            # Atomic rename
            temp_file.rename(self.storage_file)
            
            logger.info(f"💾 Successfully saved tokens to {self.storage_file}")
            logger.info(f"📊 Token data keys: {list(tokens.keys())}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to save tokens to {self.storage_file}: {e}")
            return False
    
    def save_refresh_token(self, service: str, refresh_token: str, encryption_key: str) -> bool:
        """Save encrypted refresh token for a service"""
        try:
            logger.info(f"🔐 Saving refresh token for {service}")
            logger.info(f"📏 Token length: {len(refresh_token)}")
            
            # Encrypt the token
            encrypted_token = self._encrypt_token(refresh_token, encryption_key)
            logger.info(f"🔒 Encrypted token length: {len(encrypted_token)}")
            
            # Load existing tokens
            tokens = self._load_tokens()
            
            # Update the specific service token
            tokens[service] = {
                'encrypted_refresh_token': encrypted_token,
                'last_updated': datetime.now(timezone.utc).isoformat(),
                'token_length': len(refresh_token)
            }
            
            # Save back to file
            success = self._save_tokens(tokens)
            
            if success:
                logger.info(f"✅ Successfully saved {service} refresh token")
            else:
                logger.error(f"❌ Failed to save {service} refresh token")
                
            return success
            
        except Exception as e:
            logger.error(f"❌ Error saving {service} refresh token: {e}")
            return False
    
    def load_refresh_token(self, service: str, encryption_key: str) -> Optional[str]:
        """Load and decrypt refresh token for a service"""
        try:
            logger.info(f"🔓 Loading refresh token for {service}")
            
            # Load tokens
            tokens = self._load_tokens()
            
            if service not in tokens:
                logger.warning(f"⚠️ No token found for service: {service}")
                return None
            
            service_data = tokens[service]
            encrypted_token = service_data.get('encrypted_refresh_token', '').strip()
            
            if not encrypted_token:
                logger.warning(f"⚠️ No encrypted token found for service: {service} (empty or missing)")
                return None
            
            # Decrypt the token
            refresh_token = self._decrypt_token(encrypted_token, encryption_key)
            logger.info(f"✅ Successfully loaded {service} refresh token (length: {len(refresh_token)})")
            logger.info(f"📅 Token last updated: {service_data.get('last_updated', 'unknown')}")
            
            return refresh_token
            
        except Exception as e:
            logger.error(f"❌ Error loading {service} refresh token: {e}")
            return None
    
    def get_token_info(self, service: str) -> Dict[str, Any]:
        """Get token metadata for a service"""
        tokens = self._load_tokens()
        
        if service not in tokens:
            return {'exists': False}
        
        service_data = tokens[service]
        encrypted_token = service_data.get('encrypted_refresh_token', '')
        
        # Check if the token actually has content (not just empty string)
        has_valid_token = bool(encrypted_token and encrypted_token.strip())
        
        return {
            'exists': has_valid_token,  # Only True if there's actually a token
            'last_updated': service_data.get('last_updated', 'unknown'),
            'token_length': service_data.get('token_length', 0),
            'encrypted_length': len(encrypted_token),
            'has_content': has_valid_token
        }
    
    def list_all_tokens(self) -> Dict[str, Dict[str, Any]]:
        """List all stored tokens with metadata"""
        tokens = self._load_tokens()
        
        result = {}
        for service, data in tokens.items():
            if service.startswith('_'):  # Skip metadata
                continue
                
            result[service] = {
                'last_updated': data.get('last_updated', 'unknown'),  
                'token_length': data.get('token_length', 0),
                'encrypted_length': len(data.get('encrypted_refresh_token', ''))
            }
        
        return result
    
    def delete_token(self, service: str) -> bool:
        """Delete a token for a service"""
        try:
            tokens = self._load_tokens()
            
            if service in tokens:
                del tokens[service]
                success = self._save_tokens(tokens)
                
                if success:
                    logger.info(f"✅ Successfully deleted {service} token")
                else:
                    logger.error(f"❌ Failed to delete {service} token")
                    
                return success
            else:
                logger.warning(f"⚠️ No token found to delete for service: {service}")
                return True  # Not an error if token doesn't exist
                
        except Exception as e:
            logger.error(f"❌ Error deleting {service} token: {e}")
            return False 