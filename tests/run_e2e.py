"""Run E2E tests as a standalone script (bypasses pytest env issues)."""
import sys, traceback, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from mocharpa import *
from mocharpa.plugins.base import PluginManager
from mocharpa.drivers.mock_driver import MockDriver, MockNativeElement
from mocharpa.builder.find_builder import FindBuilder
from mocharpa.pipeline import actions as a
from mocharpa.plugins.database.plugin import DatabasePlugin
from mocharpa.plugins.file.plugin import FilePlugin
from mocharpa.plugins.csv.plugin import CSVPlugin
from mocharpa.plugins.queue.plugin import QueuePlugin
from mocharpa.events import *
from mocharpa.pipeline.context import PipelineContext
from mocharpa.core.context import AutomationContext


def _build_login_page(driver):
    root = driver.root_native
    page = root.add_child(MockNativeElement(name='LoginPage', automation_id='page', control_type='Pane'))
    page.add_child(MockNativeElement(name='Username', automation_id='input_user', control_type='Edit'))
    page.add_child(MockNativeElement(name='Password', automation_id='input_pass', control_type='Edit'))
    page.add_child(MockNativeElement(name='LoginButton', automation_id='btn_login', control_type='Button'))
    table = page.add_child(MockNativeElement(name='DataTable', automation_id='tbl_data', control_type='Table'))
    for i, (name, val) in enumerate([('Alice','100'),('Bob','200'),('Eve','300')]):
        row = table.add_child(MockNativeElement(name=f'Row_{i}', automation_id=f'row_{i}', control_type='DataItem'))
        row.add_child(MockNativeElement(name=name, automation_id=f'row_{i}_name', control_type='Text'))
        row.add_child(MockNativeElement(name=val, automation_id=f'row_{i}_val', control_type='Text'))


def _make_ctx(driver=None, plugins=None):
    d = driver or MockDriver()
    if not d.is_connected:
        d.connect()
    ctx = AutomationContext(driver=d)
    return PipelineContext(driver=d, timeout=10, plugin_manager=plugins, event_bus=ctx.event_bus)


passed = 0
failed = 0

def run_test(name, fn):
    global passed, failed
    try:
        fn()
        print(f'  PASS {name}')
        passed += 1
    except Exception as e:
        print(f'  FAIL {name}: {e}')
        traceback.print_exc()
        failed += 1


print('=== E2E Scenario Tests ===')
print()

# ---- Scenario 1: Browser login flow ----
def t1():
    driver = MockDriver()
    driver.connect()
    _build_login_page(driver)
    ctx = _make_ctx(driver)
    pl = Pipeline('login')
    pl.step('type_user', lambda c: FindBuilder(context=c).id('input_user').do(lambda e: e.send_keys('admin')))
    pl.step('type_pass', lambda c: FindBuilder(context=c).id('input_pass').do(lambda e: e.send_keys('secret')))
    pl.step('click', lambda c: FindBuilder(context=c).id('btn_login').do(lambda e: e.click()))
    result = pl.run(context=ctx)
    driver.disconnect()
    assert result.success
    assert len(result.step_results) == 3
run_test('browser login flow', t1)

# ---- Scenario 2: Browser -> Database ----
def t2():
    driver = MockDriver()
    driver.connect()
    _build_login_page(driver)
    db = DatabasePlugin('sqlite:///:memory:')
    mgr = PluginManager(); mgr.register(db); mgr.start_all()
    db.execute('CREATE TABLE scraped (name TEXT, value TEXT)')
    pl = Pipeline('browser_to_db')
    def scrape(ctx):
        rows = []
        for i in range(3):
            el = FindBuilder(context=ctx).name(f'Row_{i}').get()
            if el:
                ch = el.native_element._children
                rows.append({'name': ch[0].Name, 'value': ch[1].Name if len(ch)>1 else ''})
        return rows
    pl.step('scrape', scrape)
    pl.step('insert', lambda ctx: [db.insert('scraped', r) for r in ctx.previous])
    pl.step('query', lambda ctx: db.fetch_all('SELECT * FROM scraped'))
    ctx = _make_ctx(driver, mgr)
    result = pl.run(context=ctx)
    driver.disconnect()
    assert result.success
    rows = result.step_results['query']
    assert len(rows) == 3
    assert rows[0]['name'] == 'Alice'
run_test('browser to database', t2)

# ---- Scenario 3: Browser -> File (CSV) ----
def t3():
    driver = MockDriver()
    driver.connect()
    _build_login_page(driver)
    tmp = tempfile.mkdtemp()
    csv_path = os.path.join(tmp, 'out.csv')
    fs = FilePlugin(base_dir=tmp); csv_pl = CSVPlugin()
    mgr = PluginManager(); mgr.register(fs); mgr.register(csv_pl); mgr.start_all()
    pl = Pipeline('browser_to_file')
    pl.step('scrape', lambda ctx: [{'name':'Alice','value':'100'},{'name':'Bob','value':'200'}])
    pl.step('write', a.csv_write(path=csv_path))
    pl.step('read', a.csv_read(path=csv_path))
    pl.step('verify', lambda ctx: len(ctx.previous))
    ctx = _make_ctx(driver, mgr)
    result = pl.run(context=ctx)
    driver.disconnect(); mgr.shutdown_all()
    assert result.success
    assert result.step_results['verify'] == 2
run_test('browser to file', t3)

# ---- Scenario 4: Full multi-plugin pipeline ----
def t4():
    driver = MockDriver()
    driver.connect()
    _build_login_page(driver)
    tmp = tempfile.mkdtemp()
    fs = FilePlugin(base_dir=tmp)
    q = QueuePlugin(os.path.join(tmp, 'pipe.db'))
    mgr = PluginManager(); mgr.register(fs); mgr.register(q); mgr.start_all()
    out = os.path.join(tmp, 'result.txt')
    pl = Pipeline('full_flow')
    pl.step('scrape', lambda ctx: [{'name':'Alice','val':'100'},{'name':'Bob','val':'200'}])
    pl.step('upper', lambda ctx: [{'name':r['name'].upper(),'val':r['val']} for r in ctx.previous])
    pl.step('save', lambda ctx: (fs.write_text(out, str(ctx.previous)), out)[1])
    pl.step('enqueue', lambda ctx: [q.push('rows', r) for r in ctx.step_results['upper']])
    def pop_all(ctx):
        res = []
        while True:
            m = q.pop('rows')
            if m is None: break
            res.append(m[1]); q.ack(m[0])
        return res
    pl.step('dequeue', pop_all)
    pl.step('verify', lambda ctx: len(ctx.previous)==2 and ctx.previous[0]['name']=='ALICE')
    ctx = _make_ctx(driver, mgr)
    result = pl.run(context=ctx)
    driver.disconnect(); mgr.shutdown_all()
    assert result.success
run_test('full multi-plugin pipeline', t4)

# ---- Scenario 5: Error handling ----
def t5():
    counter = {'n': 0}
    pl = Pipeline('err_handling')
    pl.step('ok', lambda ctx: 'good')
    def flaky(ctx):
        counter['n'] += 1
        if counter['n'] < 3: raise RuntimeError('transient')
        return 'recovered'
    pl.step('flaky', flaky, max_retries=2)
    pl.step('after', lambda ctx: 'done')
    result = pl.run()
    assert result.success
    assert result.step_results['after'] == 'done'
run_test('error handling with retry', t5)

# ---- Scenario 6: Event capture ----
def t6():
    driver = MockDriver(); driver.connect()
    ctx = AutomationContext(driver=driver)
    events = []
    bus = ctx.event_bus
    bus.subscribe(PipelineStartEvent, lambda e: events.append('ps'))
    bus.subscribe(PipelineEndEvent, lambda e: events.append('pe'))
    bus.subscribe(StepStartEvent, lambda e: events.append('ss'))
    bus.subscribe(StepEndEvent, lambda e: events.append('se'))
    bus.subscribe(ElementNotFoundEvent, lambda e: events.append('enf'))
    pl = Pipeline('event_cap')
    pl.step('s1', lambda c: 'ok')
    pl.step('s2', lambda c: FindBuilder(context=c).name('X').get())
    result = pl.run(context=ctx)
    driver.disconnect()
    assert result.success
    assert events == ['ps','ss','se','ss','enf','se','pe'], f'Got: {events}'
run_test('event capture full lifecycle', t6)

# ---- Scenario 7: Audit recording ----
def t7():
    pl = Pipeline('audit_rec')
    pl.step('ok', lambda ctx: 42)
    pl.step('skip', lambda ctx: 'x', condition=lambda: False)
    pl.step('err', lambda ctx: 1/0, continue_on_error=True)
    result = pl.run(audit=True)
    assert not result.success
    a = result.audit
    assert len(a.step_records) == 3
    assert a.step_records[0].status == 'ok'
    assert a.step_records[0].output == 42
    assert a.step_records[1].status == 'skipped'
    assert a.step_records[2].status == 'error'
    json_str = a.to_json()
    assert 'audit_rec' in json_str
run_test('audit recording', t7)

# ---- Scenario 8: Large data Ref ----
def t8():
    pl = Pipeline('large_data')
    pl.step('produce', lambda ctx: ctx.put_large('data', 'x'*50000))
    pl.step('consume', lambda ctx: len(ctx.previous.read_text()))
    result = pl.run()
    assert result.success
    assert result.step_results['consume'] == 50000
run_test('large data Ref handoff', t8)

# ---- Scenario 9: Queue producer-consumer ----
def t9():
    tmp = tempfile.mkdtemp()
    q = QueuePlugin(os.path.join(tmp, 'q.db'))
    mgr = PluginManager(); mgr.register(q); mgr.start_all()
    prod = Pipeline('producer')
    prod.step('push', lambda ctx: [q.push('work', {'task':f'job_{i}','data':i*10}) for i in range(5)])
    cons = Pipeline('consumer')
    def pop_all(ctx):
        res = []
        while True:
            m = q.pop('work')
            if m is None: break
            res.append(m[1]); q.ack(m[0])
        return res
    cons.step('pop', pop_all)
    ctx = _make_ctx(plugins=mgr)
    r1 = prod.run(context=ctx)
    r2 = cons.run(context=ctx)
    ctx.driver.disconnect(); mgr.shutdown_all()
    assert r1.success and r2.success
    tasks = r2.step_results['pop']
    assert len(tasks) == 5
    assert tasks[4]['data'] == 40
run_test('queue producer-consumer', t9)

# ---- Scenario 10: File operations ----
def t10():
    tmp = tempfile.mkdtemp()
    fs = FilePlugin(base_dir=tmp); fs.initialize(None)
    mgr = PluginManager(); mgr.register(fs); mgr.start_all()
    pl = Pipeline('file_ops')
    pl.step('mkdir', a.file_mkdir(path='subdir'))
    pl.step('write1', a.file_write_text(path='subdir/a.txt', content='alpha'))
    pl.step('write2', a.file_write_text(path='subdir/b.txt', content='beta'))
    pl.step('copy', a.file_copy(src='subdir/a.txt', dst='subdir/a_copy.txt'))
    pl.step('glob', a.file_glob(pattern='subdir/*.txt'))
    pl.step('exists', a.file_exists(path='subdir/a_copy.txt'))
    ctx = _make_ctx(plugins=mgr)
    result = pl.run(context=ctx)
    ctx.driver.disconnect(); mgr.shutdown_all()
    assert result.success
    assert len(result.step_results['glob']) == 3
    assert result.step_results['exists'] is True
run_test('file plugin operations', t10)

# ---- Scenario 11: Pipeline retry ----
def t11():
    counter = {'n': 0}
    pl = Pipeline('pipe_retry')
    def maybe_fail(ctx):
        counter['n'] += 1
        if counter['n'] < 3: raise RuntimeError('fail')
        return 'ok'
    pl.step('flaky', maybe_fail)
    result = pl.run(retry_count=2)
    assert result.success
    assert counter['n'] == 3
run_test('pipeline-level retry', t11)

# ---- Scenario 12: Flow control ----
def t12():
    pl = Pipeline('flow')
    pl.step('data', lambda ctx: ['a','b','c','d','e'])
    pl.step('filtered', lambda ctx: [x for x in ctx.previous if x > 'b'])
    pl.step('mapped', lambda ctx: [x.upper() for x in ctx.previous])
    result = pl.run()
    assert result.success
    assert result.step_results['mapped'] == ['C','D','E']
run_test('flow control filter+map', t12)

print()
print(f'=== {passed} passed, {failed} failed ===')
if failed:
    sys.exit(1)
