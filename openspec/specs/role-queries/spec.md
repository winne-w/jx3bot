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
