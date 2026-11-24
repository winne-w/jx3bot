## ADDED Requirements
### Requirement: Explicit kungfu aliases
Equipment commands SHALL resolve maintained Chinese aliases and case-insensitive abbreviated tokens into canonical kungfu names before loadout filtering or API calls. Unknown explicit kungfu and ambiguous tokens SHALL return clear errors, while role identity tokens SHALL retain priority. Mapping SHALL cover every catalog kungfu and live in one project Python file, without runtime network lookup.

#### Scenario: Healer alias
- WHEN 装备 桃桃白糖 秀奶 PVP is parsed
- THEN kungfu is 云裳心经 and type is 竞技对抗

#### Scenario: Ambiguous abbreviation
- WHEN tl is supplied as a kungfu option
- THEN the reply offers 铁牢律 and 天罗诡道, without fetching an arbitrary detail
