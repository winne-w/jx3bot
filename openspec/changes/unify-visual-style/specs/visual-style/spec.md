## ADDED Requirements

### Requirement: Unified Light Modern Design System Across QQ Cards and JJC Web Pages
All active QQ bot image templates (22 templates) and all JJC HTTP static pages (5 pages) SHALL share the Light Modern Design System (`--jx3-bg: #F3F6FB`, `--jx3-surface: #FFFFFF`, `--jx3-ink: #1E293B`, `--jx3-primary: #4F6EF7`, `tabular-nums` numeric alignment, and `【夏鸥】bot` brand footer).

#### Scenario: Rendering any active QQ card template
- **WHEN** any active QQ Jinja template is rendered with valid or partial upstream data
- **THEN** the rendered HTML SHALL include the unified `--jx3-*` light tokens, enable HTML auto-escaping (`{% autoescape true %}`), contain no legacy discordant backgrounds (`#89f7fe`, `#261e2c`, `#1c2130`, `#A3E4D7`) or dead local background URLs, and render at `width=760, height="ck"` (`1520px` @2x) with zero horizontal overflow.

#### Scenario: Viewing JJC public pages vs hidden sync queue page
- **WHEN** a user opens `index.html`, `jjc-ranking-stats.html`, `jjc-synced-matches.html`, or `jjc-matchups.html`
- **THEN** `index.html` and `jjc-ranking-stats.html` SHALL be byte-for-byte identical, all 4 public pages SHALL load `jjc-site.css` without stripe overlays, and none of the 4 public pages SHALL expose a link to `jjc-sync-queue.html`
- **AND WHEN** an operator directly visits `jjc-sync-queue.html`
- **THEN** the page SHALL render within the unified `.page` / `.site-header` / `.page-title-region` light shell from `jjc-site.css` while preserving all queue filter, worker status, and pagination DOM IDs.
