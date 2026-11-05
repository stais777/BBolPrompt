"""Model Windows' refusal to delete open SQLite files on a Linux test host.

The lock guard is explicit simulation; this is not native Windows execution.
"""
from contextlib import contextmanager
import errno
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from bbolprom_engine.library import Library


@contextmanager
def windows_file_locks():
    """Retain connections so GC cannot accidentally hide a missing close()."""
    import os
    real_connect=sqlite3.connect;real_unlink=os.unlink
    connections=[]
    def tracked_connect(filename,*args,**kwargs):
        base=kwargs.pop('factory',sqlite3.Connection)
        class Tracked(base):
            def __init__(self,*args,**kwargs):
                super().__init__(*args,**kwargs)
                self.test_path=str(filename);self.test_closed=False;connections.append(self)
            def close(self):
                super().close();self.test_closed=True
        return real_connect(filename,*args,factory=Tracked,**kwargs)
    def guarded_unlink(path,*args,**kwargs):
        if any(c.test_path==str(path) and not c.test_closed for c in connections):
            raise PermissionError(errno.EACCES,'Simulated Windows open SQLite file',str(path))
        return real_unlink(path,*args,**kwargs)
    try:
        with patch('sqlite3.connect',side_effect=tracked_connect),patch('os.unlink',side_effect=guarded_unlink):
            yield connections
    finally:
        for connection in connections:connection.close()


class WindowsStorage(unittest.TestCase):
    def test_backup_closes_temporary_database_before_windows_unlink(self):
        with tempfile.TemporaryDirectory() as folder:
            library=Library(Path(folder)/'library')
            cid=library.manual('등록 저장 오류 재현용 원문',[])
            with windows_file_locks() as connections:
                archive=library.backup()
                self.assertTrue(all(c.test_closed for c in connections))
                self.assertEqual(list((library.root/'backup').glob('*.sqlite3')),[])
            with zipfile.ZipFile(archive) as z:
                self.assertIsNone(z.testzip())
                restored=Path(folder)/'restored.sqlite3';restored.write_bytes(z.read('library.sqlite3'))
            con=sqlite3.connect(restored)
            try:self.assertEqual(con.execute('SELECT text FROM cards WHERE id=?',(cid,)).fetchone()[0],'등록 저장 오류 재현용 원문')
            finally:con.close()

    def test_library_transaction_closes_and_rolls_back_on_error(self):
        with tempfile.TemporaryDirectory() as folder:
            library=Library(folder)
            with windows_file_locks() as connections:
                with library.connect() as connection:connection.execute('SELECT 1')
                self.assertTrue(connections[-1].test_closed)
                with self.assertRaises(RuntimeError):
                    with library.connect() as connection:
                        connection.execute("INSERT INTO settings VALUES('must_rollback','true')")
                        raise RuntimeError('injected rollback')
                self.assertTrue(connections[-1].test_closed)
                self.assertIsNone(library.get_setting('must_rollback'))

    def test_backup_failure_closes_connections_and_removes_temporary_database(self):
        with tempfile.TemporaryDirectory() as folder:
            library=Library(folder)
            with windows_file_locks() as connections,patch('bbolprom_engine.library.zipfile.ZipFile',side_effect=PermissionError(errno.EACCES,'injected archive denial')):
                with self.assertRaises(PermissionError):library.backup()
                self.assertTrue(all(c.test_closed for c in connections))
                self.assertEqual(list((library.root/'backup').glob('*.sqlite3')),[])


if __name__=='__main__':unittest.main()
