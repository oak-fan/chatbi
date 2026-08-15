"""共享的文件能力约束常量。"""

# 分块上传最小分片大小（字节）。
FILE_CHUNK_MIN_PART_SIZE = 1 * 1024 * 1024
# 分块上传最大分片大小（字节）。
FILE_CHUNK_MAX_PART_SIZE = 10 * 1024 * 1024
# 对象键最大长度（与 sys_file_record.storage_key 保持一致）。
FILE_OBJECT_KEY_MAX_LENGTH = 128

__all__ = [
    "FILE_CHUNK_MIN_PART_SIZE",
    "FILE_CHUNK_MAX_PART_SIZE",
    "FILE_OBJECT_KEY_MAX_LENGTH",
]
