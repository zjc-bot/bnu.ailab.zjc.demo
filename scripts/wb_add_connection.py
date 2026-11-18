import json
import os
import sqlite3
import sys

DB = os.path.expandvars(
    r"%APPDATA%\MySQL Workbench\mysqlsh\plugin_data\gui_plugin\mysqlsh_gui_backend.sqlite3"
)

CAPTION = "阿里云 ECS · MySQL 8.0"
OPTIONS = {
    "scheme": "mysql",
    "user": "root",
    "host": "127.0.0.1",
    "port": 3306,
    "ssh": "root@47.118.28.10:22",
    "ssh-identity-file": r"C:\Users\ZJC\.ssh\id_rsa",
}
DESCRIPTION = "SSH 隧道 → 47.118.28.10:22，MySQL 走 127.0.0.1:3306"


def main():
    if not os.path.exists(DB):
        print("DB_NOT_FOUND", DB)
        return 2

    c = sqlite3.connect(DB)
    c.execute("PRAGMA foreign_keys=ON")

    exist = c.execute(
        "SELECT id FROM db_connection WHERE caption=?", (CAPTION,)
    ).fetchone()
    if exist:
        print("ALREADY_EXISTS id=", exist[0])
        c.close()
        return 0

    c.execute(
        """INSERT INTO db_connection(db_type, caption, description, options, settings)
           VALUES(?,?,?,?,?)""",
        ("MySQL", CAPTION, DESCRIPTION, json.dumps(OPTIONS, ensure_ascii=False), "{}"),
    )
    cid = c.execute("SELECT last_insert_rowid()").fetchone()[0]

    idx = c.execute(
        "SELECT COALESCE(MAX(`index`),-1)+1 FROM profile_has_db_connection WHERE profile_id=1 AND folder_path_id=1"
    ).fetchone()[0]

    c.execute(
        """INSERT INTO profile_has_db_connection(profile_id, db_connection_id, folder_path_id, `index`)
           VALUES(?,?,?,?)""",
        (1, cid, 1, idx),
    )
    c.commit()

    row = c.execute(
        """SELECT dc.id, dc.caption, dc.options, pdc.folder_path_id, pdc.`index`
           FROM db_connection dc
           JOIN profile_has_db_connection pdc ON pdc.db_connection_id=dc.id
           WHERE dc.id=?""",
        (cid,),
    ).fetchone()
    print("INSERTED:", row)
    c.close()
    return 0


sys.exit(main())
