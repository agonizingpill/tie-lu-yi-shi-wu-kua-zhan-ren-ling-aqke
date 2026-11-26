import {api} from '../api.js';
import {pageTitle} from '../components/layout.js';
import {status} from '../components/status.js';
import {dateTime, escape} from '../format.js';
import {showMessage} from '../forms.js';
import {store} from '../store.js';

function sampleRow(row) {
  const baseline = row.baseline_hit === null ? '—' : (row.baseline_hit ? '第 ' + row.baseline_rank + ' 名' : '未入前十二');
  const variant = row.variant_hit === null ? '—'
    : (row.variant_hit ? '第 ' + row.variant_rank + ' 名'
      : (row.variant_rank ? '第 ' + row.variant_rank + ' 名' : '低于阈值'));
  const dropped = row.baseline_hit && row.variant_hit === false;
  return '<tr' + (dropped ? ' class="audit-drop"' : '') + '><td class="mono">#' + row.search_id + '</td>'
    + '<td class="mono">' + escape(row.seal_id) + '</td><td>' + escape(dateTime(row.released_at)) + '</td>'
    + '<td>' + baseline + '</td><td>' + variant + '</td>'
    + '<td>' + (row.has_snapshot ? '' : '缺首次打分记录') + '</td></tr>';
}

function summaryBox(summary) {
  if (!summary) return '';
  return '<div class="notes"><p><b>可复算样本 ' + summary.scored + ' 张</b>'
    + ' · 原权重命中 ' + summary.baseline_hits + '（' + Math.round(summary.baseline_rate * 100) + '%）'
    + ' · 颜色减半命中 ' + summary.variant_hits + '（' + Math.round(summary.variant_rate * 100) + '%）</p>'
    + (summary.missing_snapshot ? '<p>缺首次打分记录单列 ' + summary.missing_snapshot + ' 张：#'
      + summary.missing_search_ids.map(id => escape(id)).join('、#') + '</p>' : '')
    + (summary.dropped.length ? '<p><b>跌出前十二名 ' + summary.dropped.length + ' 张：</b>'
      + summary.dropped.map(item => '#' + item.search_id + '（' + escape(item.seal_id) + ' ' + item.baseline_rank
        + '→' + (item.variant_rank || '阈值外') + '）').join('；') + '</p>' : '')
    + (summary.gained.length ? '<p>新进入前十二名 ' + summary.gained.length + ' 张：#'
      + summary.gained.map(item => escape(item.search_id)).join('、#') + '</p>' : '') + '</div>';
}

export async function audit(main) {
  main.innerHTML = pageTitle('AUDIT / 稽核', '颜色权重敏感性', '用已交付认领回放首次打分：同一批封袋分别按原权重与颜色减半排序，比较真件前十二名命中率。');
  if (store.user.role !== 'observer') {
    main.innerHTML += '<p class="empty">仅票务稽核可发起与查看权重稽核。</p>';
    return;
  }
  main.innerHTML += `<div class="domain-grid"><section class="panel"><h2>稽核轮次</h2>
      <div id="audit-message"></div><div id="audit-list"><p class="empty">读取中…</p></div></section>
    <section class="panel"><h2>本轮样本</h2><div id="audit-detail"><p class="empty">选择轮次查看样本身与命中率。</p></div></section></div>`;
  const list = main.querySelector('#audit-list');
  const detail = main.querySelector('#audit-detail');
  const message = main.querySelector('#audit-message');

  async function open(id) {
    detail.innerHTML = '<p class="empty">读取中…</p>';
    try {
      const {audit: round, samples, summary} = await api.audit(id);
      detail.innerHTML = '<p><span class="stamp">稽核 #' + round.id + '</span> 原权重 '
        + round.baseline_weight + ' / 颜色 ' + round.variant_weight + ' · ' + status(round.status)
        + ' · 开测 ' + escape(dateTime(round.started_at)) + '</p>'
        + summaryBox(summary)
        + (samples.length ? '<div class="table-wrap"><table><thead><tr><th>线索</th><th>真件封签</th><th>交付时间</th>'
          + '<th>原权重名次</th><th>减半后名次</th><th>备注</th></tr></thead><tbody>'
          + samples.map(sampleRow).join('') + '</tbody></table></div>' : '<p class="empty">本轮没有已交付样本。</p>');
    } catch (error) {
      showMessage(detail, error.message, 'error');
    }
  }

  async function refresh() {
    const rounds = await api.audits();
    list.innerHTML = '<button type="button" id="start-audit">按当前交付开新一轮</button>'
      + (rounds.length ? '<ul class="notes">' + rounds.map(round =>
        '<li><button type="button" class="secondary slim" data-audit="' + round.id + '">#' + round.id + '</button> '
        + status(round.status) + (round.status === 'running'
          ? ' <button type="button" class="slim" data-resume="' + round.id + '">续跑</button>' : '')
        + '<p>样本 ' + round.sample_count + ' 张 · 已算 ' + round.scored_count
        + ' 张 · 缺记录 ' + round.missing_snapshot + ' 张<br><small class="muted">开测 '
        + escape(dateTime(round.started_at)) + '</small></p></li>').join('') + '</ul>'
        : '<p class="empty">尚未发起稽核。</p>');
    list.querySelectorAll('[data-audit]').forEach(button => button.addEventListener('click',
      () => open(Number(button.dataset.audit))));
    list.querySelectorAll('[data-resume]').forEach(button => button.addEventListener('click', async () => {
      try {
        const outcome = await api.runAudit(Number(button.dataset.resume));
        showMessage(message, '稽核 #' + outcome.audit_id + ' 续跑 ' + outcome.processed + ' 张，剩余 ' + outcome.remaining + '。');
        await refresh();
        await open(outcome.audit_id);
      } catch (error) {
        showMessage(message, error.message, 'error');
      }
    }));
    list.querySelector('#start-audit').addEventListener('click', async () => {
      try {
        const round = await api.startAudit();
        showMessage(message, '稽核 #' + round.id + ' 已冻结样本，开始复算。');
        const outcome = await api.runAudit(round.id);
        showMessage(message, '稽核 #' + round.id + ' 复算 ' + outcome.processed + ' 张，剩余 ' + outcome.remaining + '。');
        await refresh();
        await open(round.id);
      } catch (error) {
        showMessage(message, error.message, 'error');
      }
    });
  }

  await refresh();
}
