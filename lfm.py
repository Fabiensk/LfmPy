#!/usr/bin/python3

# Command line tool to retrieve one Libre.fm history and run simple queries
# like "favorite songs for last two weeks"
#
# Rename «lfm.conf.sample» to «lfm.conf» and set your account name

import sys, http.client, urllib.request
import xml.dom.minidom
import datetime
import sqlite3
import configparser
import time

LFM_CONF = "lfm.conf"
DB_NAME = "lfm.sqlite3"

def get_node_text(node, name):
    try:
        return node.getElementsByTagName(name)[0].firstChild.data
    except:
        return None
def init_db():
    db = sqlite3.connect(DB_NAME)
    cur = db.cursor()
    cur.execute("SELECT count(*) FROM sqlite_master")
    if cur.fetchone()[0]>0:
        return db

    cur.execute("create table artist(id INTEGER PRIMARY KEY ASC);")
    cur.execute("create table album(id INTEGER PRIMARY KEY ASC, artist_id INTEGER);")
    cur.execute("create table song(id INTEGER PRIMARY KEY ASC, artist_id INTEGER);")
    cur.execute("create table artist_name(id INTEGER PRIMARY KEY ASC, name text, artist_id INTEGER, is_default BOOLEAN)")
    cur.execute("create table album_name(id INTEGER PRIMARY KEY ASC, name text, album_id INTEGER, is_default BOOLEAN)")
    cur.execute("create table song_name(id INTEGER PRIMARY KEY ASC, name text, song_id INTEGER, is_default BOOLEAN)")
    cur.execute("""create table record(timestamp INTEGER,
    log_artist TEXT, log_album TEXT, log_song TEXT,
    artist_id INTEGER, album_id INTEGER, song_id INTEGER)""")
    cur.close()
        
    return db

def get_create_artist(db, text):
    if text==None:
        return None
    text = text.strip()
    cur = db.cursor()
    sql = "SELECT artist_id from artist_name where name=?;"
    cur.execute(sql, (text, ))
    rec = cur.fetchall()
    if len(rec)==0:
        cur.execute("INSERT into artist default values;")
        parent_id = cur.lastrowid
        cur.execute("INSERT into artist_name (name, artist_id, is_default) values (?,?,?);", (text, parent_id, 1,))
        cur.close()
        return parent_id
    else:
        return rec[0][0]

def get_create(db, table, text, artist_id):
    if text==None:
        return None
    text = text.strip()
    cur = db.cursor()
    sql = """SELECT {0}_id
    from {0}_name, {0}
    where {0}.id={0}_name.{0}_id and name=? and {0}.artist_id=?;""".format(table)
    cur.execute(sql, (text, artist_id))
    rec = cur.fetchall()
    if len(rec)==0:
        cur.execute("INSERT into {0} (artist_id) values (?);".format(table), (artist_id,))
        parent_id = cur.lastrowid
        sql = "INSERT into {0}_name (name, {0}_id, is_default) values (?,?,?);".format(table)
        cur.execute(sql, (text, parent_id, 1,))
        cur.close()
        return parent_id
    else:
        return rec[0][0]
    
    
# return True if new record
def process_row(db, node):
    # extract fields
    artist = get_node_text(node, "artist")
    song = get_node_text(node, "name")
    album = get_node_text(node, "album")
    date = int(node.getElementsByTagName("date")[0].getAttribute("uts"))
    date_text = datetime.datetime.utcfromtimestamp(float(date))
    # check if already exists
    try:
        cur = db.cursor()
        rec = cur.execute("select count(*)>0 from record where timestamp=?", (date,)).fetchone()
        if rec[0]==1:
            return False
    finally:
        cur.close()
    # create data
    artist_id = get_create_artist(db, artist)
    song_id = None
    album_id = None
    if artist!=None:
        song_id = get_create(db, "song", song, artist_id)
        album_id = get_create(db, "album", album, artist_id)
    cur = db.cursor()
    cur.execute("INSERT into record (timestamp, log_artist, log_album, log_song, artist_id, album_id, song_id) values (?,?,?,?,?,?,?)",
                (date, artist, album, song, artist_id, album_id, song_id))
    cur.close()
    return True

# return True if some records where new on this page
def process_page(db, user, page):
    LIMIT = 50

    url = "http://alpha.libre.fm/2.0/?method=user.getrecenttracks&user={0}&page={1}&limit={2}"
    url = url.format(user, page, LIMIT)
    print(url)
    if True:
        rsp = urllib.request.urlopen(url)
        dom = xml.dom.minidom.parseString(rsp.read())
    else:
        dom = xml.dom.minidom.parseString(open("sample.xml", "rt").read())
    has_new = False
    node = None
    # print(dom.getElementsByTagName('track'))
    for node in dom.getElementsByTagName('track'):
        if process_row(db, node)==True:
            has_new = True
    return node!=None and has_new

def update(db, user):
    MAX_IDENT_PAGES = 2
    page = 1
    ident_pages = 0
    while True:
        print("Processed page", page)
        if process_page(db, user, page)==False:
            ident_pages += 1
            if ident_pages>=MAX_IDENT_PAGES:
                break
        page += 1
    db.commit()
    db.close()

def do_stats_artist(db, type, d):
    cur = db.cursor()
    sql = """select count(*) as cnt, name
    from record, {0}_name

    where record.{0}_id={0}_name.{0}_id
    and timestamp>?

    group by {0}_name.name
    order by cnt desc""".format(type)
    # print(sql)
    cur.execute(sql, (d,))
    for rec in cur.fetchall():
        print(rec)

def do_stats(db, type, d):
    cur = db.cursor()
    sql = """select count(*) as cnt, {0}_name.name, artist_name.name
    from record, {0}, {0}_name, artist_name

    where {0}.id={0}_name.{0}_id
    and artist_name.artist_id=record.artist_id
    and record.{0}_id={0}.id
    and {0}_name.is_default=1
    and artist_name.is_default=1
    and timestamp>?

    group by {0}_name.name, artist_name.name
    order by cnt desc""".format(type)
    # print(sql)
    cur.execute(sql, (d,))
    for rec in cur.fetchall():
        print(rec)

def find_artist_name(db, name):
    cur = db.cursor()
    sql = "SELECT artist_id from artist_name where name=?;"
    cur.execute(sql, (name, ))
    rec = cur.fetchall()
    if len(rec)==0:
        print("Did not find artist name '{0}'".format(name))
        return None
    return rec[0][0]


def alias(db, table, other, new):
    if table!="artist":
        return
    new_id = find_artist_name(db, new)
    if new_id==None:
        return
    other_id = find_artist_name(db, other)
    if new_id==None:
        return
    cur = db.cursor()
    cur.execute("UPDATE record set artist_id=? where artist_id=?;", (new_id, other_id))
    cur.execute("UPDATE song set artist_id=? where artist_id=?;", (new_id, other_id))
    cur.execute("UPDATE album set artist_id=? where artist_id=?;", (new_id, other_id))
    cur.execute("UPDATE artist_name set is_default=0 where artist_id=?;", (other_id,))
    db.commit()
    db.close()

def syntax(msg=None):
    if msg!=None:
        print("Syntax error: {0}\n".format(msg))
    print("""Syntax:
\tlfm.py update : retrieve your data to the local database
\tlfm.py OBJECT [ PERIOD ] : display the top artist/song/album for a given period
\t\tOBJECT := { artist | song | album }
\t\tPERIOD := { day | week | month | year } [ MULTIPLIER ]
\t\t\tIf not provided, display since the world began
\t\tMULTIPLIER : number of days/weeks/... (may be a float number)
\tlfm.py alias artist OLD NEW : for the current and future data, consider that
\t\tOLD and NEW are the same artist, make him appear as NEW in the reports
""")
    sys.exit(0 if msg==None else 1)

def main():
    db = init_db()
    cfg = configparser.ConfigParser()
    cfg.read(LFM_CONF)
    user = cfg['config']['user']

    del sys.argv[0]
    if len(sys.argv)==0:
        syntax("No argument provided")
        return
    cmd = sys.argv[0]
    del sys.argv[0]
    if cmd=="help":
        syntax()
    elif cmd=="update":
        update(db, user)
    elif cmd=="alias":
        if len(sys.argv)!=3:
            syntax("Not enough arguments for alias")
        cmd = sys.argv[0]
        del sys.argv[0]
        if cmd not in ("artist"):
            syntax("Invalid alias object")
        alias(db, cmd, sys.argv[0], sys.argv[1])
    else:
        if cmd not in ("artist", "song", "album"):
            syntax("Bad report type")
        target = cmd
        
        d = 0
        if len(sys.argv)>0:
            cmd = sys.argv[0]
            
            mult = 1
            del sys.argv[0]
            if len(sys.argv)>0:
                mult = float(sys.argv[0])

            if cmd=="all":
                d = 0
            elif cmd=="day":
                d = time.time()-60*60*24*mult
            elif cmd=="week":
                d = time.time()-60*60*24*7*mult
            elif cmd=="month":
                d = time.time()-60*60*24*7*30*mult
            elif cmd=="year":
                d = time.time()-60*60*24*365*mult
            else:
                print("syntax error: period")
                return
        if target=="artist":
            do_stats_artist(db, target, d)
        else:        
            do_stats(db, target, d)

main()
