"""Windows user-scoped DPAPI; never persist plaintext or invent encryption."""
import ctypes
from ctypes import wintypes
import os
import re
import base64
import secrets


class SecretError(ValueError): pass


def validate_token(token):
    if not isinstance(token,str) or not re.fullmatch(r'[!-~]{16,256}',token):
        raise SecretError('MCP令牌须为16至256位无空格ASCII字符')
    return token


def _transform(data, decrypt=False):
    if os.name!='nt':raise SecretError('当前系统不支持Windows DPAPI安全令牌存储')
    class Blob(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buffer=ctypes.create_string_buffer(data)
    source=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)))
    target=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
    if decrypt:
        function=crypt.CryptUnprotectData
        function.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    else:
        function=crypt.CryptProtectData
        function.argtypes=[ctypes.POINTER(Blob),wintypes.LPCWSTR,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    function.restype=wintypes.BOOL
    if not function(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target)):
        raise SecretError('安全令牌存储不可用，请在当前Windows账号下重新配置令牌')
    try:return ctypes.string_at(target.data,target.size)
    finally:kernel.LocalFree(target.data)


AES_PREFIX=b'CCAE1\x00'
AAD=b'CampusClaw:MCP:token:v1'


def backend_mode():return os.environ.get('CAMPUSCLAW_SECRET_BACKEND') or ('dpapi' if os.name=='nt' else 'aesgcm')


def aes_key(value=None):
    try:
        value=os.environ.get('CAMPUSCLAW_MCP_ENCRYPTION_KEY','') if value is None else value
        key=base64.b64decode(value.encode('ascii'),altchars=b'-_',validate=True)
        if len(key)!=32:raise ValueError()
        return key
    except (ValueError,UnicodeError):raise SecretError('MCP加密密钥缺失或无效，必须是base64编码的32字节随机密钥') from None


def aes_encrypt(token,key):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:raise SecretError('未安装锁定的部署加密依赖，禁止明文降级') from None
    nonce=secrets.token_bytes(12)
    return AES_PREFIX+nonce+AESGCM(key).encrypt(nonce,validate_token(token).encode('ascii'),AAD)


def aes_decrypt(blob,key):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if not blob.startswith(AES_PREFIX) or len(blob)<len(AES_PREFIX)+28:raise ValueError()
        payload=blob[len(AES_PREFIX):]
        return validate_token(AESGCM(key).decrypt(payload[:12],payload[12:],AAD).decode('ascii'))
    except Exception:raise SecretError('MCP令牌无法认证解密；请恢复原密钥或执行离线密钥轮换，不得清空数据') from None


def protect(token):
    mode=backend_mode()
    if mode=='aesgcm':return aes_encrypt(token,aes_key())
    if mode!='dpapi':raise SecretError('不支持的安全存储后端')
    return _transform(validate_token(token).encode('ascii'))
def unprotect(blob):
    try:
        data=bytes(blob);mode=backend_mode()
        if mode=='aesgcm':return aes_decrypt(data,aes_key())
        if mode!='dpapi' or data.startswith(AES_PREFIX):raise SecretError('令牌密文属于不同运行环境，不允许自动迁移')
        return validate_token(_transform(data,True).decode('ascii'))
    except (ValueError,TypeError,UnicodeError):raise SecretError('无法读取安全令牌，请重新配置') from None
