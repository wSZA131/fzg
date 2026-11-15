// 学习计划模块
document.addEventListener('DOMContentLoaded', function() {
  console.log('页面加载完成，开始初始化学习计划...');
  const API_BASE = window.ApiUtils.getApiBase();
  const parseApiResponse = window.ApiUtils.parseApiResponse;
  const withSuggestion = window.ApiUtils.withSuggestion;

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function(char) {
      return {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      }[char];
    });
  }
  
  function getUserId() {
    return window.UserContext ? window.UserContext.getUserId() : 'default_user';
  }
  
  // 页面加载时获取计划
  loadPlans();
  loadReviewReminders();

  window.addEventListener('knowledge:updated', function () {
    loadPlans();
    loadReviewReminders();
  });

  if (window.UserContext) {
    window.UserContext.onChange(function () {
      loadPlans();
      loadReviewReminders();
    });
  }
  
  // 绑定添加按钮点击事件
  const addBtn = document.getElementById('add-plan-btn');
  if (addBtn) {
    console.log('找到添加按钮，绑定事件');
    addBtn.addEventListener('click', handleAddPlan);
  } else {
    console.error('❌ 错误：找不到 #add-plan-btn 按钮！');
  }
  
  // 绑定回车键
  const taskInput = document.getElementById('new-plan-task');
  if (taskInput) {
    taskInput.addEventListener('keypress', function(e) {
      if (e.key === 'Enter') {
        handleAddPlan();
      }
    });
  }
  
  // 动态事件委托（处理打勾和删除）
  const planList = document.getElementById('plan-list');
  if (planList) {
    // 打勾功能
    planList.addEventListener('change', function(e) {
      if (e.target.classList.contains('plan-check')) {
        const planItem = e.target.closest('.plan-item');
        const planId = planItem.dataset.id;
        const isCompleted = e.target.checked;
        
        console.log('切换完成状态:', planId, isCompleted);
        
        // 先乐观更新 UI，失败时回滚，避免用户以为已保存。
        planItem.classList.toggle('completed', isCompleted);
        syncPlanOverviewFromDom();

        updateTaskStatus(planId, isCompleted).then(function (ok) {
          if (ok) return;
          e.target.checked = !isCompleted;
          planItem.classList.toggle('completed', !isCompleted);
          syncPlanOverviewFromDom();
          alert('计划状态保存失败，请检查网络后重试。');
        });
      }
    });
    
    // 删除功能
    planList.addEventListener('click', function(e) {
      if (e.target.classList.contains('delete-btn')) {
        const planItem = e.target.closest('.plan-item');
        const planId = planItem.dataset.id;
        
        if (confirm('确定要删除这个学习计划吗？')) {
          console.log('删除计划:', planId);
          
          // 删除动画
          planItem.style.opacity = '0';
          planItem.style.transform = 'translateX(20px)';
          
          setTimeout(() => {
            planItem.remove();
            // 更新后端；失败时重新拉取，恢复被乐观移除的条目。
            deleteTaskBackend(planId).then(function (ok) {
              if (!ok) loadPlans();
            });

            // 检查是否为空
            if (document.querySelectorAll('#plan-list .plan-item').length === 0) {
              showEmptyState();
            }
            syncPlanOverviewFromDom();
          }, 300);
        }
      }
    });
  } else {
    console.error('❌ 错误：找不到 #plan-list 容器！');
  }
  
  // ========== 核心功能函数 ==========

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = String(value);
  }

  function applyPlanMetrics(total, done) {
    const totalCount = Math.max(0, Number(total) || 0);
    const doneCount = Math.min(totalCount, Math.max(0, Number(done) || 0));
    const remaining = totalCount - doneCount;

    setText('entryPlanDoneCount', doneCount);
    setText('entryPlanTotalCount', totalCount);
    setText('entryPlanRemainingCount', remaining);
    setText('entryPlanListMeta', totalCount ? `${totalCount} 项` : '暂无任务');

    const badge = document.getElementById('entryPlanNavCount');
    if (badge) {
      badge.textContent = String(remaining);
      badge.hidden = remaining <= 0;
    }
  }

  function updatePlanOverview(plans) {
    const rows = Array.isArray(plans) ? plans : [];
    const done = rows.filter(function (plan) {
      return !!(plan && plan.completed);
    }).length;
    applyPlanMetrics(rows.length, done);
  }

  function syncPlanOverviewFromDom() {
    const items = Array.from(document.querySelectorAll('#plan-list .plan-item'));
    const done = items.filter(function (item) {
      return item.classList.contains('completed');
    }).length;
    applyPlanMetrics(items.length, done);
  }

  function setPlanFormStatus(text, isError) {
    const status = document.getElementById('entryPlanFormStatus');
    if (!status) return;
    status.textContent = text || '';
    status.classList.toggle('error', !!isError);
    status.hidden = !text;
  }

  function syncPlanDrawerDate() {
    const dateEl = document.getElementById('entryPlanDrawerDate');
    if (!dateEl) return;
    try {
      dateEl.textContent = new Intl.DateTimeFormat('zh-CN', {
        month: 'long',
        day: 'numeric',
        weekday: 'short'
      }).format(new Date());
    } catch (error) {
      dateEl.textContent = '今天';
    }
  }

  function openPlanDrawer() {
    const drawer = document.getElementById('entryPlanDrawer');
    const launcher = document.getElementById('entryPlanLauncherBtn');
    if (!drawer) return;

    if (window.PageShell && typeof window.PageShell.closeGlobalSidebar === 'function') {
      window.PageShell.closeGlobalSidebar();
    }

    syncPlanDrawerDate();
    setPlanFormStatus('');
    drawer.classList.add('open');
    drawer.setAttribute('aria-hidden', 'false');
    document.body.classList.add('entry-plan-drawer-open');
    if (launcher) {
      launcher.classList.add('active');
      launcher.setAttribute('aria-expanded', 'true');
    }
    loadPlans();
    loadReviewReminders();
  }

  function closePlanDrawer() {
    const drawer = document.getElementById('entryPlanDrawer');
    const launcher = document.getElementById('entryPlanLauncherBtn');
    if (!drawer) return;

    drawer.classList.remove('open');
    drawer.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('entry-plan-drawer-open');
    if (launcher) {
      launcher.classList.remove('active');
      launcher.setAttribute('aria-expanded', 'false');
    }
  }

  function initPlanDrawer() {
    const drawer = document.getElementById('entryPlanDrawer');
    const launcher = document.getElementById('entryPlanLauncherBtn');
    const closeBtn = document.getElementById('entryPlanDrawerClose');
    if (!drawer || !launcher || !closeBtn) return;
    if (launcher.dataset.planDrawerBound === '1') return;
    launcher.dataset.planDrawerBound = '1';

    syncPlanDrawerDate();
    launcher.addEventListener('click', function () {
      if (drawer.classList.contains('open')) {
        closePlanDrawer();
      } else {
        openPlanDrawer();
      }
    });
    closeBtn.addEventListener('click', closePlanDrawer);
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && drawer.classList.contains('open')) {
        closePlanDrawer();
      }
    });
  }
  
  // 加载计划
  async function loadPlans() {
    console.log('正在从后端加载学习计划...');
    
    try {
      const userId = getUserId();
      const response = await fetch(`${API_BASE}/api/plans?user_id=${userId}`);
      const data = await parseApiResponse(response);
      console.log('后端返回数据:', data);

      renderPlans(data.plans || []);
    } catch (error) {
      console.error('加载计划失败:', error);
      updatePlanOverview([]);
      const planList = document.getElementById('plan-list');
      if (planList) {
        planList.innerHTML = `<div class="empty-state is-error">${escapeHtml(withSuggestion('学习计划加载失败', error, '刷新页面或稍后重试'))}</div>`;
      }
    }
  }
  
  // 渲染计划列表
  function renderPlans(plans) {
    const planList = document.getElementById('plan-list');
    if (!planList) {
      console.error('找不到 #plan-list 元素');
      return;
    }

    const rows = Array.isArray(plans) ? plans : [];
    updatePlanOverview(rows);
    
    if (rows.length === 0) {
      showEmptyState();
      return;
    }
    
    // 按时间排序
    rows.sort((a, b) => String(a.time || '').localeCompare(String(b.time || '')));
    
    planList.innerHTML = rows.map(plan => `
      <div class="plan-item ${plan.completed ? 'completed' : ''}" data-id="${escapeHtml(plan.id)}">
        <input type="checkbox" class="plan-check" ${plan.completed ? 'checked' : ''}>
        <div class="plan-content">
          <span class="plan-time">${escapeHtml(plan.time)}</span>
          <span class="plan-task">${escapeHtml(plan.task)}</span>
        </div>
        <button class="delete-btn" title="删除计划">×</button>
      </div>
    `).join('');
    
    console.log(`已渲染 ${rows.length} 个计划`);
  }
  
  // 显示空状态
  function showEmptyState() {
    const planList = document.getElementById('plan-list');
    if (planList) {
      planList.innerHTML = `
        <div class="empty-state">
          暂无学习计划<br>
          <small>从上方快速添加你的第一个任务</small>
        </div>
      `;
    }
  }
  
  // 添加计划
  async function handleAddPlan() {
    console.log('点击添加按钮');
    
    const timeInput = document.getElementById('new-plan-time');
    const taskInput = document.getElementById('new-plan-task');
    const addBtn = document.getElementById('add-plan-btn');
    
    if (!timeInput || !taskInput || !addBtn) {
      console.error('找不到输入框或按钮');
      return;
    }
    
    const time = timeInput.value;
    const task = taskInput.value.trim();
    
    console.log('输入的值:', { time, task });
    setPlanFormStatus('');
    
    // 验证
    if (!time) {
      setPlanFormStatus('请选择计划时间。', true);
      timeInput.focus();
      return;
    }
    
    if (!task) {
      setPlanFormStatus('请输入学习任务。', true);
      taskInput.focus();
      return;
    }
    
    // 禁用按钮防止重复点击
    addBtn.disabled = true;
    addBtn.textContent = '添加中...';
    
    try {
      const response = await fetch(`${API_BASE}/api/plans`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify({
          user_id: getUserId(),
          time: time,
          task: task
        })
      });
      
      console.log('后端响应状态:', response.status);
      
      const data = await parseApiResponse(response);
      console.log('后端响应数据:', data);

      // 清空输入
      timeInput.value = '';
      taskInput.value = '';
      taskInput.focus();

      // 重新加载计划
      await loadPlans();

      setPlanFormStatus('已加入今日计划。');
    } catch (error) {
      console.error('添加失败:', error);
      setPlanFormStatus(withSuggestion('添加失败', error, '检查输入后重试'), true);
    } finally {
      // 恢复按钮
      addBtn.disabled = false;
      addBtn.textContent = '添加计划';
    }
  }
  
  // 更新任务状态
  async function updateTaskStatus(planId, isCompleted) {
    try {
      const response = await fetch(`${API_BASE}/api/plans/${planId}`, {
        method: 'PUT',
        headers: { 
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify({
          user_id: getUserId(),
          completed: isCompleted
        })
      });
      
      await parseApiResponse(response);
      return true;
    } catch (error) {
      console.error('状态更新失败:', error);
      return false;
    }
  }
  
  // 删除任务（后端）
  async function deleteTaskBackend(planId) {
    try {
      const response = await fetch(`${API_BASE}/api/plans/${planId}`, {
        method: 'DELETE',
        headers: { 
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify({ user_id: getUserId() })
      });

      await parseApiResponse(response);
      return true;
    } catch (error) {
      console.error('后端删除失败:', error);
      alert(withSuggestion('删除计划失败', error, '刷新页面后重试'));
      return false;
    }
  }

  async function loadReviewReminders() {
    const list = document.getElementById('review-reminder-list');
    if (!list) return;

    try {
      const userId = getUserId();
      const response = await fetch(`${API_BASE}/api/review/reminders?user_id=${userId}`);
      const data = await parseApiResponse(response);

      if (!data.due_items || data.due_items.length === 0) {
        list.innerHTML = '<div class="review-reminder-empty">今天没有紧急复习项，继续保持。</div>';
        return;
      }

      list.innerHTML = data.due_items.slice(0, 4).map(item => {
        const pct = Math.round((item.mastery || 0) * 100);
        return `
          <div class="review-reminder-item">
            <span>${escapeHtml(item.concept)}</span>
            <strong>掌握度 ${pct}%</strong>
          </div>
        `;
      }).join('');
    } catch (error) {
      console.error('加载复习提醒失败:', error);
      list.innerHTML = `<div class="review-reminder-error">${escapeHtml(withSuggestion('提醒加载失败', error, '刷新页面或稍后重试'))}</div>`;
    }
  }

  initPlanDrawer();
});
