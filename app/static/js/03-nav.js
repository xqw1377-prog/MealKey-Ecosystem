/* MealKey UI — sidebar, workspace mode, section scroll, rails */

function setNavGroupOpen(groupKey, open) {
  const group = qs(`[data-nav-group="${groupKey}"]`);
  if (!group) return;
  const toggle = group.querySelector("[data-nav-toggle]");
  const sub = group.querySelector(".nav-sub");
  group.classList.toggle("open", open);
  if (toggle) toggle.setAttribute("aria-expanded", open ? "true" : "false");
  if (sub) sub.hidden = !open;
}

function syncSidebarNav(targetId, { stayHome = false } = {}) {
  const navKey = stayHome ? "today" : NAV_KEY_BY_SECTION[targetId] || null;
  qsa(".nav-item[data-nav-key]").forEach((item) => {
    const isActive = item.dataset.navKey === navKey;
    item.classList.toggle("active", isActive);
    item.setAttribute("aria-current", isActive ? "page" : "false");
  });
  qsa(".nav-sub-item").forEach((item) => {
    const isActive = !stayHome && item.dataset.scrollTarget === targetId;
    item.classList.toggle("active", isActive);
  });
  setNavGroupOpen("skills", navKey === "skills");
}

function isMobileHomeViewport() {
  return window.matchMedia("(max-width: 900px)").matches;
}

function syncMobileSheetBackdrop() {
  const backdrop = qs("#mkSheetBackdrop");
  if (!backdrop) return;
  const open =
    document.body.classList.contains("show-work-rail") ||
    document.body.classList.contains("right-rail-open");
  backdrop.hidden = !open;
  backdrop.setAttribute("aria-hidden", open ? "false" : "true");
}

function syncMobileTabbar(activeTab) {
  const tab = activeTab || "today";
  state.mobileTab = tab;
  qsa("[data-mobile-tab]").forEach((btn) => {
    const on = btn.dataset.mobileTab === tab;
    btn.classList.toggle("is-active", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
  });
}

function closeMobileSheets() {
  if (!isMobileHomeViewport()) return;
  state.opsRailCollapsed = true;
  state.rightRailOpen = false;
  document.body.classList.add("ops-rail-collapsed");
  document.body.classList.remove("show-work-rail", "right-rail-open");
  const toggle = qs("#mkWorkRailToggleBtn");
  if (toggle) {
    toggle.setAttribute("aria-expanded", "false");
    toggle.title = "展开左侧工作线程";
  }
  const rightToggle = qs("#toggleRightRailBtn");
  if (rightToggle) {
    rightToggle.setAttribute("aria-pressed", "false");
    rightToggle.classList.remove("active");
  }
  syncMobileSheetBackdrop();
  syncMobileTabbar("today");
}

function openMobilePanel(panel) {
  if (!isMobileHomeViewport()) return;
  if (panel === "threads") {
    state.opsRailCollapsed = false;
    state.rightRailOpen = false;
    document.body.classList.add("ops-rail-collapsed", "show-work-rail");
    document.body.classList.remove("right-rail-open");
    syncMobileTabbar("threads");
  } else if (panel === "diary") {
    state.opsRailCollapsed = true;
    state.rightRailOpen = true;
    document.body.classList.add("ops-rail-collapsed", "right-rail-open");
    document.body.classList.remove("show-work-rail");
    syncMobileTabbar("diary");
  } else {
    closeMobileSheets();
    syncMobileTabbar("today");
    return;
  }
  const workToggle = qs("#mkWorkRailToggleBtn");
  if (workToggle) {
    workToggle.setAttribute("aria-expanded", panel === "threads" ? "true" : "false");
  }
  const rightToggle = qs("#toggleRightRailBtn");
  if (rightToggle) {
    rightToggle.setAttribute("aria-pressed", panel === "diary" ? "true" : "false");
    rightToggle.classList.toggle("active", panel === "diary");
  }
  syncMobileSheetBackdrop();
}

function setRightRailOpen(open) {
  state.rightRailOpen = Boolean(open);
  document.body.classList.toggle("right-rail-open", state.rightRailOpen);
  try { localStorage.setItem("mk_right_rail_open", state.rightRailOpen ? "1" : "0"); } catch (_) { /* ignore */ }
  const rightColumn = qs("#rightColumn");
  if (rightColumn) {
    rightColumn.dataset.collapsed = state.rightRailOpen ? "false" : "true";
    const onHome = document.body.classList.contains("view-home");
    // 窄屏日记用 #mkContextRail，旧 rightColumn 保持隐藏
    rightColumn.hidden = isMobileHomeViewport() || !onHome || !state.rightRailOpen;
    rightColumn.setAttribute("aria-hidden", rightColumn.hidden ? "true" : "false");
  }
  const toggle = qs("#toggleRightRailBtn");
  if (toggle) {
    toggle.setAttribute("aria-pressed", state.rightRailOpen ? "true" : "false");
    toggle.classList.toggle("active", state.rightRailOpen);
  }
  if (isMobileHomeViewport()) {
    if (state.rightRailOpen) {
      document.body.classList.remove("show-work-rail");
      state.opsRailCollapsed = true;
      syncMobileTabbar("diary");
    } else if (!document.body.classList.contains("show-work-rail")) {
      syncMobileTabbar("today");
    }
    syncMobileSheetBackdrop();
  }
}

function applyWorkspaceMode(targetId) {
  const stayHome = isHomeWorkspace(targetId);
  document.body.classList.toggle("view-home", stayHome);
  document.body.classList.toggle("view-module", !stayHome);
  document.body.classList.toggle("workspace-focus", !stayHome);

  const homeShell = qs("#homeShell");
  if (homeShell) {
    homeShell.hidden = !stayHome;
    homeShell.setAttribute("aria-hidden", stayHome ? "false" : "true");
  }

  const deck = qs("#section-workspace-deck");
  if (deck) {
    deck.hidden = stayHome;
    deck.setAttribute("aria-hidden", stayHome ? "true" : "false");
    deck.classList.toggle("module-focus", !stayHome);
  }

  // 首页：全宽状态页；模块页再显示侧栏
  setRightRailOpen(false);
  return stayHome;
}

function scrollToSection(id) {
  const requestedId = id || state.activeWorkspace || "section-overview";
  const stayHome = isHomeWorkspace(requestedId);
  const targetId = stayHome ? "section-overview" : requestedId;
  const view = workspaceView(targetId);
  state.activeWorkspace = targetId;

  applyWorkspaceMode(targetId);
  syncSidebarNav(requestedId === "section-home" ? "section-overview" : requestedId, { stayHome });

  qsa("[data-workspace-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.workspacePanel === view.panel);
  });

  renderWorkspaceHeader(view, { isHome: stayHome });
  renderTopbar();

  const stage = qs("#workspaceStage");
  if (stage) stage.scrollTop = 0;
  const panel = qs(`[data-workspace-panel="${view.panel}"]`);
  if (panel) panel.scrollTop = 0;
  const main = qs("#mainColumn");
  if (main) main.scrollTop = 0;

  if (stayHome && requestedId !== "section-overview" && requestedId !== "section-home") {
    const anchor = qs(`#${requestedId}`);
    if (anchor) {
      requestAnimationFrame(() => {
        anchor.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
  }

  if (window.matchMedia("(max-width: 860px)").matches) {
    setSidebarOpen(false);
  }

  // 离开首页进入专家/模块舱时再懒加载全量 dashboard
  if (!stayHome) {
    ensureFullDashboard().catch(() => null);
  }
}

function setOpsRailCollapsed(collapsed) {
  state.opsRailCollapsed = Boolean(collapsed);
  const mobile = isMobileHomeViewport();
  try {
    if (!mobile) {
      localStorage.setItem("mk_ops_rail_collapsed", state.opsRailCollapsed ? "1" : "0");
    }
  } catch (_) {
    /* ignore */
  }
  if (mobile) {
    // 窄屏：中栏独占；Logo / 底栏控制左栏抽屉（show-work-rail）
    document.body.classList.add("ops-rail-collapsed");
    document.body.classList.toggle("show-work-rail", !state.opsRailCollapsed);
    if (!state.opsRailCollapsed) {
      state.rightRailOpen = false;
      document.body.classList.remove("right-rail-open");
      syncMobileTabbar("threads");
    } else if (!state.rightRailOpen) {
      syncMobileTabbar("today");
    }
    syncMobileSheetBackdrop();
  } else {
    document.body.classList.remove("show-work-rail");
    document.body.classList.toggle("ops-rail-collapsed", state.opsRailCollapsed);
    syncMobileSheetBackdrop();
  }
  const toggle = qs("#mkWorkRailToggleBtn");
  if (toggle) {
    toggle.setAttribute("aria-expanded", state.opsRailCollapsed ? "false" : "true");
    toggle.title = state.opsRailCollapsed ? "展开左侧工作线程" : "收起左侧工作线程";
  }
  const reopen = qs("#mkWorkRailReopenBtn");
  if (reopen) reopen.hidden = true;
}

function initOpsRailCollapsed() {
  // 手机首页默认只看「今天」主舞台，避免一进页就弹出左栏
  if (isMobileHomeViewport()) {
    setOpsRailCollapsed(true);
    setRightRailOpen(false);
    syncMobileTabbar("today");
    return;
  }
  let collapsed = false;
  let rightOpen = false;
  try {
    collapsed = localStorage.getItem("mk_ops_rail_collapsed") === "1";
    // 整页刷新不再把右栏(经营日记)关掉 — 桌面端恢复用户上次的选择
    rightOpen = localStorage.getItem("mk_right_rail_open") === "1";
  } catch (_) {
    collapsed = false;
    rightOpen = false;
  }
  setOpsRailCollapsed(collapsed);
  setRightRailOpen(rightOpen);
}

function setSidebarOpen(open) {
  const sidebar = qs("#sidebar");
  const toggle = qs("#sidebarToggle");
  const backdrop = qs("#sidebarBackdrop");
  if (!sidebar) return;
  const isMobile = window.matchMedia("(max-width: 860px)").matches;
  if (!isMobile) {
    sidebar.classList.remove("collapsed");
    if (toggle) toggle.setAttribute("aria-expanded", "true");
    if (backdrop) {
      backdrop.hidden = true;
      backdrop.classList.remove("show");
    }
    document.body.classList.remove("sidebar-open");
    return;
  }
  sidebar.classList.toggle("collapsed", !open);
  if (toggle) toggle.setAttribute("aria-expanded", String(open));
  if (backdrop) {
    backdrop.hidden = !open;
    backdrop.classList.toggle("show", open);
  }
  document.body.classList.toggle("sidebar-open", open);
}

function syncSidebarForViewport() {
  const isMobile = window.matchMedia("(max-width: 860px)").matches;
  setSidebarOpen(!isMobile);
}

function toggleSidebar() {
  const sidebar = qs("#sidebar");
  if (!sidebar) return;
  const isMobile = window.matchMedia("(max-width: 860px)").matches;
  if (!isMobile) return;
  setSidebarOpen(sidebar.classList.contains("collapsed"));
}

function bindSidebarNav() {
  qsa(".nav-item[data-scroll-target], .nav-sub-item[data-scroll-target]").forEach((item) => {
    item.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const groupKey = item.dataset.navToggle;
      if (groupKey) {
        const group = item.closest(".nav-group");
        const isOpen = group?.classList.contains("open");
        // 已展开时再点分组标题：只收起，避免 scroll/sync 又把它打开
        if (isOpen) {
          setNavGroupOpen(groupKey, false);
          return;
        }
        setNavGroupOpen(groupKey, true);
      }
      scrollToSection(item.dataset.scrollTarget);
    });
  });
}
