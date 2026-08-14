console.info("MealKey: app logic moved to /static/js/*.js — loaded via index.html");

// Decision Core frontend functions

async function calculateCampaign(rule, skuData) {
  if (!state.currentStoreId) return null;
  try {
    return await fetchJson('/stores/' + state.currentStoreId + '/campaign/calculate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rule: rule, ...skuData }),
    });
  } catch (e) { notifyError('活动测算失败：' + e.message); return null; }
}

async function campaignDecideAndExecute(rule, skuData) {
  if (!state.currentStoreId) return;
  try {
    const result = await fetchJson('/stores/' + state.currentStoreId + '/campaign/decide-and-execute', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rule: rule, ...skuData }),
    });
    const d = result.decision || {};
    var verdictLabel = { GREEN: '建议参加', YELLOW: '限量测试', RED: '不建议', BLACK: '无法判断' }[d.verdict] || d.verdict;
    if (result.recommendation_id) {
      var lines = [verdictLabel + ': ' + (d.strategy || '')];
      if (d.calc && d.calc.profit_per_order_with_campaign != null) {
        lines.push('单均利润 ¥' + d.calc.profit_per_order_with_campaign.toFixed(1));
      }
      if (result.message) lines.push(result.message);
      appendChatMessage('assistant', lines.join('\n'));
      await loadDashboard(state.currentStoreId);
      notifySuccess('已创建活动测试任务');
    } else {
      appendChatMessage('assistant', verdictLabel + ': ' + (d.reasoning || d.strategy || ''));
    }
  } catch (e) { notifyError('活动决策失败：' + e.message); }
}

async function diagnoseProfit(current, baseline, ordersCurrent, ordersBaseline) {
  if (!state.currentStoreId) return null;
  try {
    const result = await fetchJson('/stores/' + state.currentStoreId + '/profit/diagnose', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current: current, baseline: baseline, orders_current: ordersCurrent, orders_baseline: ordersBaseline }),
    });
    if (result.conclusion) appendChatMessage('assistant', result.conclusion);
    return result;
  } catch (e) { notifyError('利润诊断失败：' + e.message); return null; }
}

async function previewRecommendation(recId) {
  if (!recId) return null;
  try {
    return await fetchJson('/workspace/recommendations/' + recId + '/preview');
  } catch (e) { notifyError('预览失败：' + e.message); return null; }
}

async function rollbackRecommendation(recId) {
  if (!recId) return;
  try {
    const result = await fetchJson('/workspace/recommendations/' + recId + '/rollback', { method: 'POST' });
    await loadDashboard(state.currentStoreId);
    notifySuccess(result.detail || '已回滚');
  } catch (e) { notifyError('回滚失败：' + e.message); }
}

