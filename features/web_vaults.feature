Feature: Vault management through the web UI
  The UI should support vault creation, rename, delete, selection,
  and show helpful validation messages.

  Scenario: Create a vault successfully
    Given the service is unlocked with passphrase "passphrase"
    When I create a vault named "dev" from the UI
    Then the last event says "Vault created."
    And vault "dev" exists in storage

  Scenario: Creating a duplicate vault shows an error
    Given the service is unlocked with passphrase "passphrase"
    And a vault named "dev" exists
    When I create a vault named "dev" from the UI
    Then the last event says "Vault already exists."

  Scenario: Renaming a vault works
    Given the service is unlocked with passphrase "passphrase"
    And a vault named "dev" exists
    When I rename vault "dev" to "dev-renamed" from the UI
    Then the last event says "Vault renamed."
    And vault "dev-renamed" exists in storage
    And vault "dev" does not exist in storage

  Scenario: Renaming a vault to an existing name shows an error
    Given the service is unlocked with passphrase "passphrase"
    And a vault named "alpha" exists
    And a vault named "beta" exists
    When I rename vault "alpha" to "beta" from the UI
    Then the last event says "A vault with that name already exists."

  Scenario: Deleting a selected vault removes it
    Given the service is unlocked with passphrase "passphrase"
    And a vault named "dev" exists
    And the vault "dev" is selected in the UI
    When I delete vault "dev" from the UI
    Then the last event says "Vault deleted."
    And vault "dev" does not exist in storage
    And the page contains text "Select a vault, secret, or metadata field to generate a helper."

  Scenario: Selecting an invalid vault falls back to the first sorted vault
    Given the service is unlocked with passphrase "passphrase"
    And a vault named "beta" exists
    And a vault named "alpha" exists
    When I open the UI with query string "vault=missing"
    Then the selected vault shown is "alpha"

  Scenario: Locked users cannot create a vault
    Given the service has been initialized with passphrase "passphrase" and is now locked
    When I create a vault named "dev" from the UI
    Then the last event says "Service is locked."
