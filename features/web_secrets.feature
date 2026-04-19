Feature: Secret and metadata management through the web UI
  The UI should create, update, rename, delete, and explain secrets correctly.

  Scenario: Create a secret and then add metadata
    Given the service is unlocked with passphrase "passphrase"
    And a vault named "dev" exists
    When I create secret "api-key" in vault "dev" with value "secret-value" from the UI
    Then the last event says "Secret created."
    And secret "api-key" exists in vault "dev"
    When I set metadata key "env" to "dev" for secret "api-key" in vault "dev" from the UI
    Then the last event says "Metadata saved."
    And secret "api-key" in vault "dev" has metadata key "env" with value "dev"

  Scenario: Adding metadata to an existing secret saves immediately for a new key
    Given the service is unlocked with passphrase "passphrase"
    And a vault named "dev" exists
    And a secret "api-key" exists in vault "dev" with value "secret-value"
    When I set metadata key "owner" to "miguel" for secret "api-key" in vault "dev" from the UI
    Then the last event says "Metadata saved."
    And secret "api-key" in vault "dev" has metadata key "owner" with value "miguel"

  Scenario: Duplicate metadata key shows overwrite confirmation
    Given the service is unlocked with passphrase "passphrase"
    And a vault named "dev" exists
    And a secret "api-key" exists in vault "dev" with value "secret-value"
    And secret "api-key" in vault "dev" has metadata key "owner" with value "miguel"
    When I set metadata key "owner" to "team-alpha" for secret "api-key" in vault "dev" from the UI
    Then overwrite confirmation is shown for metadata key "owner" from value "miguel" to value "team-alpha"
    And secret "api-key" in vault "dev" has metadata key "owner" with value "miguel"

  Scenario: Confirming metadata overwrite updates the value
    Given the service is unlocked with passphrase "passphrase"
    And a vault named "dev" exists
    And a secret "api-key" exists in vault "dev" with value "secret-value"
    And secret "api-key" in vault "dev" has metadata key "owner" with value "miguel"
    When I set metadata key "owner" to "team-alpha" for secret "api-key" in vault "dev" from the UI
    And I confirm the metadata overwrite
    Then the last event says "Metadata saved."
    And secret "api-key" in vault "dev" has metadata key "owner" with value "team-alpha"

  Scenario: Canceling metadata overwrite preserves the current value
    Given the service is unlocked with passphrase "passphrase"
    And a vault named "dev" exists
    And a secret "api-key" exists in vault "dev" with value "secret-value"
    And secret "api-key" in vault "dev" has metadata key "owner" with value "miguel"
    When I set metadata key "owner" to "team-alpha" for secret "api-key" in vault "dev" from the UI
    And I cancel the metadata overwrite
    Then overwrite confirmation is not shown
    And secret "api-key" in vault "dev" has metadata key "owner" with value "miguel"

  Scenario: Creating a duplicate secret shows an error
    Given the service is unlocked with passphrase "passphrase"
    And a vault named "dev" exists
    And a secret "api-key" exists in vault "dev" with value "secret-value"
    When I create secret "api-key" in vault "dev" with value "other-value" from the UI
    Then the last event says "Secret already exists in this vault."

  Scenario: Rename, update, and delete a secret
    Given the service is unlocked with passphrase "passphrase"
    And a vault named "dev" exists
    And a secret "api-key" exists in vault "dev" with value "secret-value"
    When I rename secret "api-key" in vault "dev" to "api-key-v2" from the UI
    Then the last event says "Secret renamed."
    And secret "api-key-v2" exists in vault "dev"
    And secret "api-key" does not exist in vault "dev"
    When I update secret "api-key-v2" in vault "dev" to value "rotated-value" from the UI
    Then the last event says "Secret updated."
    And secret "api-key-v2" in vault "dev" has value "rotated-value"
    When I delete secret "api-key-v2" in vault "dev" from the UI
    Then the last event says "Secret deleted."
    And secret "api-key-v2" does not exist in vault "dev"

  Scenario: Metadata can be deleted
    Given the service is unlocked with passphrase "passphrase"
    And a vault named "dev" exists
    And a secret "api-key" exists in vault "dev" with value "secret-value"
    And secret "api-key" in vault "dev" has metadata key "owner" with value "miguel"
    When I delete metadata key "owner" for secret "api-key" in vault "dev" from the UI
    Then the last event says "Metadata deleted."
    And secret "api-key" in vault "dev" does not have metadata key "owner"

  Scenario: Metadata helper path appears for a selected field
    Given the service is unlocked with passphrase "passphrase"
    And a vault named "dev" exists
    And a secret "api-key" exists in vault "dev" with value "secret-value"
    And secret "api-key" in vault "dev" has metadata key "env" with value "dev"
    When I open the UI with query string "vault=dev&secret=api-key&expanded=api-key&field=env&target=metadata-field"
    Then the helper path "/api/v1/vaults/dev/secrets/api-key/metadata" is shown
    And the helper snippet contains "response.json()"

  Scenario: Locked users cannot create secrets
    Given the service has been initialized with passphrase "passphrase" and is now locked
    When I create secret "api-key" in vault "dev" with value "secret-value" from the UI
    Then the last event says "Service is locked."
