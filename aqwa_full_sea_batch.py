"""Run sourced H00 sea states sequentially using the verified wide-band workflow."""
from datetime import datetime, timezone
from html import escape
import json
from types import MappingProxyType
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from aqwa_full_sea import (FINE, digest, get_h00_full_sea, preview_h00_full_sea,
                           read_h00_full_sea, start_h00_full_sea)
from aqwa_frequency_jobs import timestamp, write_status
from aqwa_config import OUTPUT, WORK, solver_path

RUNS = WORK / 'full_sea_batches'
REPORTS = OUTPUT / 'full_sea_batches'
ACTIVE = {'queued', 'running'}
CASE_WAIT = 500
CASE_FIELDS = ('case_name', 'sea_state', 'source_kind', 'source_note')
MOTIONS = MappingProxyType({'surge':'纵荡', 'sway':'横荡', 'heave':'垂荡',
                           'roll':'横摇', 'pitch':'纵摇', 'yaw':'艏摇'})
LINES = ('line_1', 'line_2', 'line_3')


def _json_bytes(data, *, canonical=False):
    return (json.dumps(data, ensure_ascii=False, allow_nan=False, sort_keys=canonical,
                       indent=None if canonical else 2) + '\n').encode('utf-8')


def preview_h00_full_sea_batch(cases):
    """Check 2–4 distinctly named long-crested seas; leave unsupported bands blocked."""
    if not isinstance(cases, list) or not 2 <= len(cases) <= 4:
        raise ValueError('Provide 2–4 H00 sea-state cases.')
    rows, names, specs = [], set(), set()
    for entry in cases:
        if not isinstance(entry, dict) or set(entry) != set(CASE_FIELDS):
            raise ValueError('Each row requires case_name, sea_state, source_kind and source_note.')
        name = entry['case_name']
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60 or not name.strip().isprintable():
            raise ValueError('Each case_name must be printable and 1–60 characters long.')
        name = name.strip()
        if name.casefold() in names:
            raise ValueError('Case names must be unique.')
        names.add(name.casefold())
        note = entry['source_note']
        if not isinstance(note, str) or not note.strip().isprintable():
            raise ValueError('Each source_note must be printable.')
        p = preview_h00_full_sea(entry['sea_state'], entry['source_kind'], note)
        sea = p['sea_state']
        key = (sea['hs_m'], sea['tp_s'], sea['gamma'], sea['direction_deg'] % 360)
        if key in specs:
            raise ValueError('Physically identical cases are duplicates (-180 and 180 are the same heading).')
        specs.add(key)
        rows.append({'case_name':name, 'sea_state':sea, 'sea_state_source':p['sea_state_source'],
                     'status':'ready' if p['ready_for_native_comparison'] else 'blocked',
                     **{k:p[k] for k in ('preview_sha256', 'comparison_blocker',
                                       'reference_wave_band_hz', 'reference_wave_band_energy_fraction',
                                       'wide_check_band_hz', 'wide_check_band_energy_fraction',
                                       'minimum_suggested_hydrodynamic_endpoints_hz')}})
    return {'case':'H00', 'status':'preview_only', 'cases':rows,
            'ready_count':sum(r['status'] == 'ready' for r in rows),
            'verified_hydrodynamic_band_hz':p['verified_hydrodynamic_band_hz'],
            'verified_hydrodynamic_point_count':len(FINE),
            'mean_wind_m_s':8, 'fluctuating_wind_modeled':False,
            'time_domain_run':False, 'formal_site_result':False,
            'preview_sha256':digest(_json_bytes(rows, canonical=True))}


def _folder(batch_id):
    if not isinstance(batch_id, str) or not re.fullmatch(r'[a-f0-9]{32}', batch_id):
        raise ValueError('Use the 32-character full-sea batch_id.')
    folder = RUNS / batch_id
    if not folder.is_dir() or folder.resolve() != folder:
        raise ValueError('Full-sea batch not found.')
    return folder


def _state(batch_id):
    path = _folder(batch_id) / 'frequency_job.json'
    if not path.is_file() or path.resolve() != path:
        raise ValueError('Full-sea batch status unavailable.')
    state = json.loads(path.read_text(encoding='utf-8'))
    if state.get('batch_id') != batch_id or state.get('case') != 'H00':
        raise ValueError('Full-sea batch metadata does not match.')
    return state


def get_h00_full_sea_batch(batch_id):
    """Return job and child progress without starting a solve."""
    state = _state(batch_id)
    if state['status'] in ACTIVE:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(state['updated_at'])).total_seconds()
        if age > CASE_WAIT + 30:
            return {**state, 'status':'unresponsive', 'reason':'No recent batch progress.'}
        active = next((row for row in state['cases'] if row['status'] == 'running'), None)
        if active and active.get('run_id'):
            child = get_h00_full_sea(active['run_id'])
            state['active_child'] = {k:child[k] for k in ('run_id','status','stage') if k in child}
    return state


def start_h00_full_sea_batch(cases, expected_preview_sha256):
    """Submit the exact preview and queue only supported sea states."""
    preview = preview_h00_full_sea_batch(cases)
    if expected_preview_sha256 != preview['preview_sha256']:
        raise ValueError('Batch inputs changed; precheck again and use the new preview_sha256.')
    if not preview['ready_count']:
        raise ValueError('No sea state has sufficient verified frequency support; no solver started.')
    solver_path()
    batch_id = uuid.uuid4().hex
    folder = RUNS / batch_id
    folder.mkdir(parents=True)
    state = {**preview, 'batch_id':batch_id, 'status':'queued', 'created_at':timestamp(),
             'cases':[dict(r, status='pending' if r['status'] == 'ready' else 'blocked')
                      for r in preview['cases']]}
    write_status(folder, state)
    try:
        with (folder / 'batch_console.txt').open('xb') as log:
            subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), batch_id],
                             cwd=folder, stdin=subprocess.DEVNULL, stdout=log,
                             stderr=subprocess.STDOUT, close_fds=True,
                             creationflags=getattr(subprocess,'DETACHED_PROCESS',0) |
                                           getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0))
    except OSError as exc:
        state.update(status='failed', reason=str(exc))
        write_status(folder, state)
    return state


def _await_child(run_id):
    end = time.monotonic() + CASE_WAIT
    while True:
        state = get_h00_full_sea(run_id)
        if state['status'] not in ACTIVE:
            return state
        if time.monotonic() >= end:
            return {**state, 'status':'unresponsive', 'reason':'Child run exceeded the batch wait limit.'}
        time.sleep(.4)


def _largest_reported_change(groups):
    ratios = [test['relative_to_reference'] for group in groups.values() for test in group.values()
              if test['relative_to_reference'] is not None]
    return max(ratios, default=None)


def _summarize(child):
    wide = child['native_cases']['wider_band']
    return {'usable_for_numerical_comparison':child['numerical_screen_pass'],
            'motion_standard_deviation':wide['motion_standard_deviation'],
            'motion_units':{k:('deg' if k in ('roll','pitch','yaw') else 'm') for k in MOTIONS},
            'fairlead_dynamic_tension_standard_deviation_n':wide['fairlead_dynamic_tension_standard_deviation_n'],
            'native_band_hz':wide['band_hz'], 'native_frequency_points_hz':wide['line_frequency_hz'],
            'native_band_limited_significant_wave_height_m':wide['native_band_limited_significant_wave_height_m'],
            'max_grid_relative_change':_largest_reported_change(child['frequency_grid_comparison']),
            'max_band_relative_change':_largest_reported_change(child['frequency_band_comparison']),
            'numerical_screen_threshold':child['threshold'],
            'damping_sensitivity_warning':child['damping_sensitivity_warning'],
            'damping_case_failures':child['damping_case_failures'],
            'report_json':child['report_json']}


def _html(report):
    rows = report['cases']
    chart_rows = [r for r in rows if r.get('result',{}).get('usable_for_numerical_comparison')]
    scale = max((r['result']['motion_standard_deviation'][k]
                 for r in chart_rows for k in ('roll','pitch')), default=1) or 1
    sources = {'commissioning':'调试工况', 'research_assumption':'研究假设',
               'site_data':'场址数据（未核验）', 'literature':'文献（未核验）'}
    labels = {'completed':'已计算', 'blocked':'频带不足，未求解', 'failed':'求解或结果读取失败',
              'unresponsive':'求解无响应', 'skipped':'未提交'}

    def percent(value):
        return '—' if value is None else f'{value:.2%}'

    def band(values):
        return '—' if not values else f'{values[0]:.4f}–{values[1]:.4f} Hz'

    def chart(key):
        entries = []
        for row in chart_rows:
            v = row['result']['motion_standard_deviation'][key]
            entries.append(f'<div class="bar"><span>{escape(row["case_name"])}</span>'
                           f'<div class="track"><div class="fill" style="width:{v/scale:.4%}"></div></div>'
                           f'<strong>{v:.4f}°</strong></div>')
        return f'<section><h3>{MOTIONS[key]}</h3>{"".join(entries) or "<p>暂无通过筛查的工况。</p>"}</section>'

    overview, stats = [], []
    for r in rows:
        sea, src = r['sea_state'], r['sea_state_source']
        name = escape(r['case_name'])
        result = r.get('result')
        reason = r.get('reason','')
        if r['status'] == 'blocked':
            reason = f'建议支持端点：{band(r["minimum_suggested_hydrodynamic_endpoints_hz"])}；未外推'
        if result:
            grid = percent(result['max_grid_relative_change'])
            widen = percent(result['max_band_relative_change'])
            screen = '通过' if result['usable_for_numerical_comparison'] else '未通过'
            damping = '有警告' if result['damping_sensitivity_warning'] else '未触发警告'
            reason = f'筛查{screen}；频点加密 {grid} / 频带扩展 {widen}；试算阻尼：{damping}'
            values = ''.join(f'<td>{result["motion_standard_deviation"][k]:.5g}</td>' for k in MOTIONS)
            values += ''.join(f'<td>{result["fairlead_dynamic_tension_standard_deviation_n"][k]/1000:.5g}</td>'
                              for k in LINES)
            stats.append(f'<tr><th scope="row">{name}</th><td>{screen}</td>'
                         f'<td>{band(result["native_band_hz"])}</td>{values}</tr>')
        overview.append(f'<tr><th scope="row">{name}</th><td>{sea["hs_m"]:g}</td>'
                        f'<td>{sea["tp_s"]:g}</td><td>{sea["gamma"]:g}</td><td>{sea["direction_deg"]}°</td>'
                        f'<td>{sources[src["kind"]]}：{escape(src["note"])}</td>'
                        f'<td>{percent(r["wide_check_band_energy_fraction"])}</td>'
                        f'<td>{labels[r["status"]]}<br>{escape(reason)}</td></tr>')
    heads = ''.join(f'<th>{title} ({"m" if k in ("surge","sway","heave") else "°"})</th>'
                    for k,title in MOTIONS.items())
    heads += ''.join(f'<th>系泊线 {i} (kN)</th>' for i in range(1,4))
    status = {'completed':'全部完成', 'partial':'部分完成', 'failed':'无已计算工况'}[report['status']]
    notice = ('<p class="note"><strong>离线演示 · 合成数据 · 未调用 AQWA</strong></p>'
              if report.get('data_mode') == 'synthetic_replay' else '')
    return f"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>H00 宽频海况对比</title>
<style>
*{{box-sizing:border-box}}body{{background:#edf3f8;color:#102940;font:15px/1.55 system-ui,sans-serif;margin:0}}
main{{max-width:1200px;margin:auto;padding:28px}}h1,h2,h3{{line-height:1.25}}h1{{margin-top:0}}p{{margin:8px 0}}
article,section{{background:white;border:1px solid #dbe5ee;border-radius:12px;padding:16px;margin:16px 0}}
.charts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:16px}}
.charts section{{margin:0}}.bar{{display:grid;grid-template-columns:8em 1fr 5em;gap:8px;align-items:center;margin:12px 0}}
.bar span,td,th{{overflow-wrap:anywhere}}.track{{height:12px;background:#e6eef8;border-radius:3px;overflow:hidden}}
.fill{{height:100%;background:#176585}}.table{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}
th,td{{border-bottom:1px solid #e1e7ed;text-align:left;padding:8px;vertical-align:top}}thead{{background:#e6f0f7}}
.note{{color:#385168}}.waves{{min-width:640px}}.results{{min-width:860px;white-space:nowrap}}
</style>
<main><header><h1>H00 宽频海况对比</h1>
<p>{status}：{report['completed_count']} / {len(rows)} 组已计算。水动力频带设置：{len(FINE)} 点、{band(report['verified_hydrodynamic_band_hz'])}。</p>
{notice}
<p class="note">8 m/s 平均风预载＋一阶长峰随机波；未计算脉动风或时域响应。海况来源与阻尼未独立核验，结果仅作频域诊断。</p></header>
<article><h2>横摇与纵摇标准差</h2><p class="note">仅绘制通过数值筛查的工况，两图共用 0–{scale:.4f}° 标尺，采用扩展积分频带。</p>
<div class="charts">{chart('roll')}{chart('pitch')}</div></article>
<article><h2>海况输入与频带筛查</h2><div class="table"><table class="waves"><thead><tr><th>工况</th><th>Hs (m)</th>
<th>Tp (s)</th><th>γ</th><th>浪向</th><th>海况来源</th><th>扩展谱覆盖率</th><th>运行与筛查结果</th></tr></thead>
<tbody>{''.join(overview)}</tbody></table></div>
<p class="note">加密/扩展一栏显示各响应的最大相对变化；接近零的响应按绝对容差并行筛查。不代表规范合格。</p></article>
<article><h2>六自由度与系泊动态张力标准差</h2><div class="table"><table class="results"><thead><tr><th>工况</th><th>筛查</th>
<th>扩展积分频带</th>{heads}</tr></thead><tbody>{''.join(stats) or '<tr><td colspan="12">无计算结果</td></tr>'}</tbody></table></div>
<p class="note">系泊张力为导缆点动态分量的标准差，不是总张力或极值。</p></article></main></html>
"""


def worker(batch_id):
    folder, state = _folder(batch_id), _state(batch_id)
    if state['status'] != 'queued':
        raise ValueError('Full-sea batch is not queued.')
    with (folder / '.worker_started').open('x'):
        pass
    try:
        state['status'] = 'running'
        write_status(folder, state)
        stop = False
        for row in state['cases']:
            if row['status'] == 'blocked':
                continue
            if stop:
                row.update(status='skipped', reason='上一个求解未确认终止，避免启动重叠计算。')
                continue
            src = row['sea_state_source']
            try:
                queued = start_h00_full_sea(row['sea_state'], src['kind'], src['note'], row['preview_sha256'])
                row.update(status='running', run_id=queued['run_id'])
                write_status(folder, state)
            except (OSError, ValueError) as exc:
                row.update(status='failed', reason=str(exc))
                stop = True
                write_status(folder, state)
                continue
            try:
                child = _await_child(row['run_id'])
            except (OSError, ValueError) as exc:
                child = {'status':'unresponsive', 'reason':str(exc)}
            if child['status'] == 'completed':
                try:
                    row.update(status='completed', result=_summarize(read_h00_full_sea(row['run_id'])))
                except (OSError, ValueError, KeyError) as exc:
                    row.update(status='failed', reason=str(exc))
            else:
                row.update(status=child['status'], reason=child.get('reason','No completed child report.'))
                stop = child['status'] != 'failed'
            write_status(folder, state)
        count = sum(r['status'] == 'completed' for r in state['cases'])
        status = 'completed' if count == len(state['cases']) else ('partial' if count else 'failed')
        report = {**state, 'status':status, 'completed_count':count, 'completed_at':timestamp()}
        out = REPORTS / batch_id
        out.mkdir(parents=True)
        raw = _json_bytes(report)
        html = _html(report).encode('utf-8')
        for filename, data in (('sea_state_comparison.json', raw), ('sea_state_comparison.html', html)):
            with (out / filename).open('xb') as f:
                f.write(data)
        state.update(status=status, completed_count=count, report_json=str(out/'sea_state_comparison.json'),
                     report_html=str(out/'sea_state_comparison.html'),
                     report_sha256=digest(raw), report_html_sha256=digest(html))
        write_status(folder, state)
    except Exception as exc:
        state.update(status='failed', reason=str(exc))
        write_status(folder, state)
        raise


def read_h00_full_sea_batch(batch_id):
    """Read the completed batch and confirm that its JSON and HTML still match."""
    state = _state(batch_id)
    if state['status'] in ACTIVE or 'report_sha256' not in state:
        raise ValueError('No finished full-sea batch report is available.')
    folder = REPORTS / batch_id
    raw = {}
    for ext, key in (('json','report_sha256'), ('html','report_html_sha256')):
        path = folder / ('sea_state_comparison.' + ext)
        if path.resolve(strict=True) != path:
            raise ValueError('Unexpected full-sea batch report path.')
        raw[ext] = path.read_bytes()
        if digest(raw[ext]) != state[key]:
            raise ValueError('Batch report no longer matches the published checksum.')
    return {**json.loads(raw['json']), 'report_json':state['report_json'], 'report_html':state['report_html']}


if __name__ == '__main__' and len(sys.argv) == 2:
    worker(sys.argv[1])
