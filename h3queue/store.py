import contextlib, hashlib, json, os, sqlite3, time, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def home():
    return Path(os.environ.get('H3_QUEUE_HOME', ROOT / '.state')).expanduser().resolve()

def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

@contextlib.contextmanager
def db():
    home().mkdir(parents=True, exist_ok=True, mode=0o700)
    c = sqlite3.connect(home() / 'queue.sqlite3', timeout=20)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA foreign_keys=ON')
    if c.execute('PRAGMA user_version').fetchone()[0] < 2:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL,
          title TEXT NOT NULL, spec TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
          priority INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL,
          output TEXT, output_sha TEXT, error TEXT, attempt_id TEXT);
        CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, job_id TEXT REFERENCES jobs(id),
          started REAL NOT NULL, finished REAL, status TEXT NOT NULL, directory TEXT NOT NULL,
          pid INTEGER, elapsed REAL, error TEXT);
        CREATE TABLE IF NOT EXISTS cache(fingerprint TEXT PRIMARY KEY, output TEXT NOT NULL,
          sha TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS benchmarks(source TEXT PRIMARY KEY, profile TEXT NOT NULL,
          width INTEGER NOT NULL, height INTEGER NOT NULL, frames INTEGER NOT NULL,
          elapsed REAL NOT NULL, machine TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, time REAL NOT NULL,
          job_id TEXT, kind TEXT NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS telemetry(id INTEGER PRIMARY KEY AUTOINCREMENT,time REAL NOT NULL,data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS energy_metrics(source TEXT PRIMARY KEY,profile TEXT NOT NULL,machine TEXT NOT NULL,chip_w REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS jobs_scheduling ON jobs(status,priority DESC,created);
        CREATE INDEX IF NOT EXISTS attempts_active ON attempts(status,started);
        CREATE INDEX IF NOT EXISTS benchmark_profile ON benchmarks(profile,machine);
        ''')
        defaults = {'mode':'paused', 'window':{'start':'00:00','end':'07:00','timezone':'Asia/Shanghai'},
                    'idle_minutes':10, 'require_idle':True, 'stop_at_end':True,
                    'deployment':str(Path.home()/'coding/base-local-modal'), 'worker_heartbeat':0}
        from .safety import DEFAULTS
        defaults.update(safety=DEFAULTS,telemetry_totals={},thermal_alert={},safety_latch=None)
        for k,v in defaults.items():
            c.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',(k,json.dumps(v)))
        c.execute('PRAGMA user_version=2')
        c.commit()
    if c.execute('PRAGMA user_version').fetchone()[0] < 3:
        c.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',('smart_idle_minutes','10'))
        c.execute('PRAGMA user_version=3');c.commit()
    if c.execute('PRAGMA user_version').fetchone()[0] < 4:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS provider_metrics(
          source TEXT PRIMARY KEY,provider TEXT NOT NULL,metric_key TEXT NOT NULL,
          units REAL NOT NULL,elapsed REAL NOT NULL,machine TEXT NOT NULL,
          chip_w REAL,created REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS provider_metrics_lookup ON provider_metrics(provider,metric_key,machine);
        PRAGMA user_version=4;
        ''')
    try:
        yield c
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()

def get(c,key):
    return json.loads(c.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()[0])

def setv(c,key,value):
    c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,json.dumps(value)))

def event(c,kind,job=None,**data):
    c.execute('INSERT INTO events(time,job_id,kind,data) VALUES(?,?,?,?)',
              (time.time(),job,kind,json.dumps(data,ensure_ascii=False)))

def atomic_json(path,value):
    path=Path(path);tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False));tmp.replace(path)
    finally:tmp.unlink(missing_ok=True)
