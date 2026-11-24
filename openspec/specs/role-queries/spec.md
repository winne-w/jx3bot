## Requirements
### Requirement: Equipment and attributes
The bot SHALL support 装备/属性/装分 with group-bound or explicit servers and display all collected equipment, attribute panel and collection time from /calcd/attribute.
#### Scenario: Missing collected data
- WHEN the upstream has no equipment or attributes
- THEN the bot returns a clear no-collected-data message
### Requirement: Current role online status
The bot SHALL support 在线/在线状态/角色在线 via a fresh POST JSON request for the resolved role.
#### Scenario: App login without game login
- WHEN appLogin is true and gameLogin/onlineStatus is false
- THEN the bot reports game offline
#### Scenario: Ambiguous response
- WHEN no unique same-server role or no explicit boolean game status is available
- THEN the bot reports unknown instead of offline

### Requirement: Equipment item icons
Equipment screenshots SHALL display available JX3BOX item icons and short stone level labels, preserving all equipment and attributes.
#### Scenario: Missing or unavailable icon
- WHEN an icon ID is missing or the bounded image fetch fails validation
- THEN its original name remains visible and the equipment query still renders

## Equipment mobile view and collected loadout filters
装备、属性、装分支持完整心法和PVE/秘境挑战、PVP/竞技对抗、休闲、通用，含心法=/类型=。无筛选使用/calcd/attribute；两项指定使用/calcd/detail且format=calcd；单项指定先/calcd/records筛选，唯一最新有效采集时间决定组合，缺少可靠时间/并列候选要求补全，未收录明确提示。不得回退其他组合，须校验响应身份及心法类型；显示实际赛季采集时间，不提供历史赛季选择。

760宽图片显示12项治疗/攻击/坦克核心指标、全部装备、精炼/镶嵌及短属性来源，名字32px、核心34px；百分比仅使用上游percent，内部ASCII代码不展示且保留原数据。375宽有效装备名>=14px、核心>=16px，无核心数值截断/行横向溢出；外部图标失败保留文本。

## Kungfu alias search
### Requirement: Explicit kungfu aliases
Equipment commands SHALL resolve maintained Chinese aliases and case-insensitive abbreviated tokens into canonical kungfu names before loadout filtering or API calls. Unknown explicit kungfu and ambiguous tokens SHALL return clear errors, while role identity tokens SHALL retain priority. Mapping SHALL cover every catalog kungfu and live in one project Python file, without runtime network lookup.

#### Scenario: Healer alias
- WHEN 装备 桃桃白糖 秀奶 PVP is parsed
- THEN kungfu is 云裳心经 and type is 竞技对抗

#### Scenario: Ambiguous abbreviation
- WHEN tl is supplied as a kungfu option
- THEN the reply offers 铁牢律 and 天罗诡道, without fetching an arbitrary detail
