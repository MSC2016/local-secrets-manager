Feature: Read-only API behavior as seen from the web app product
  The API should reflect locked and unlocked states and expose secret content only when unlocked.

  Scenario: Status API reports locked state by default
    When I request the API path "/api/v1/status"
    Then the API response status is 200
    And the JSON field "locked" is true
    And the JSON field "unlocked" is false

  Scenario: Secret API is blocked while locked
    Given the service has been initialized with passphrase "passphrase" and is now locked
    And a vault named "dev" exists
    And a secret "api-key" exists in vault "dev" with value "secret-value"
    And I lock the service from the UI
    When I request the API path "/api/v1/vaults/dev/secrets/api-key"
    Then the API response status is 423
    And the JSON field "error" equals "Service is locked."

  Scenario: Secret API returns value after unlocking
    Given the service is unlocked with passphrase "passphrase"
    And a vault named "dev" exists
    And a secret "api-key" exists in vault "dev" with value "secret-value"
    When I request the API path "/api/v1/vaults/dev/secrets/api-key"
    Then the API response status is 200
    And the JSON field "value" equals "secret-value"
    And the JSON field "name" is absent
    And the JSON field "vault" is absent
    And the JSON field "metadata" is absent

  Scenario: Metadata API returns metadata fields without the secret payload
    Given the service is unlocked with passphrase "passphrase"
    And a vault named "dev" exists
    And a secret "api-key" exists in vault "dev" with value "secret-value"
    And secret "api-key" in vault "dev" has metadata key "env" with value "dev"
    When I request the API path "/api/v1/vaults/dev/secrets/api-key/metadata"
    Then the API response status is 200
    And the JSON field "env" equals "dev"
    And the JSON field "value" is absent
    And the JSON field "name" is absent
    And the JSON field "vault" is absent
    And the JSON field "metadata" is absent

  Scenario: Passphrase change preserves API access with the new passphrase
    Given the service is unlocked with passphrase "passphrase"
    And a vault named "dev" exists
    And a secret "api-key" exists in vault "dev" with value "secret-value"
    When I change the passphrase from "passphrase" to "rotated" from the UI
    Then the last event says "Passphrase changed."
    And the log contains text "Passphrase changed."
    When I lock the service from the UI
    And I unlock with passphrase "rotated"
    Then the merged status says "Unlocked · Ready"
    And unlocking with passphrase "passphrase" fails with message "Incorrect passphrase for the existing database."
