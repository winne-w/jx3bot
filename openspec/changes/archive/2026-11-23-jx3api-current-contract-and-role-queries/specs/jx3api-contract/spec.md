## ADDED Requirements
### Requirement: Current JX3API contract
All 13 existing endpoints and the two role query endpoints SHALL interpret integer body status separately from HTTP status, preserve legacy payload contracts, and reject malformed success responses. Required tokens SHALL be sent as headers.
#### Scenario: Business rejection over HTTP 200
- WHEN the upstream returns status=403 with detail text
- THEN the command reports failure, does not claim no records, and does not cache it as a successful query
#### Scenario: Alternate data sources
- WHEN the request targets m.pvp.xoyo.com or another non-JX3API host
- THEN its existing response and authentication contract remains unchanged
