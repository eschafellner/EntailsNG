from .texts import TEXTS


class BackupError(Exception):
    def __init__(self, key):
        self.key = key
        super().__init__(TEXTS.get(key, TEXTS['backup_err_operation']))
