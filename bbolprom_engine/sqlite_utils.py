"""SQLite transactions whose context also closes the file handle.

sqlite3.Connection.__exit__ commits/rolls back but does NOT close. Windows
cannot remove temporary databases while those connections remain open.
"""
import sqlite3


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()
