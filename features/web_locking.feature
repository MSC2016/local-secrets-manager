Feature: Locking and session controls
  The web UI should clearly reflect database lifecycle, locking, and timer behavior.

  Scenario: Home page starts with initialization controls when database is missing
    Given the web home page is open
    Then the merged status says "Locked · Setup required"
    And the top status panel is collapsed
    And the page has no top banner
    And the page contains text "Initialize Database"
    And the page contains text "Database file is missing. Initialize a new database to begin."
    And the page contains a password input named "passphrase"

  Scenario: Database initialization from the UI succeeds
    When I initialize the database with passphrase "passphrase" from the UI
    Then the last event says "Database initialized. Unlock it to continue."
    And the page has no top banner
    And the page contains text "Ready"
    And the page contains text "Database created successfully. Unlock it with the new passphrase."
    And the page does not contain text "Database is initialized. Unlock it with its passphrase, or reset it to replace all stored data."
    And the log contains text "Database initialized. Unlock it to continue."

  Scenario: Unlock succeeds after initialization
    Given the database is initialized with passphrase "passphrase"
    When I unlock with passphrase "passphrase"
    Then the merged status says "Unlocked · Ready"
    And the last event says "Service unlocked."
    And the log contains text "Service unlocked."

  Scenario: Wrong passphrase is rejected after initialization
    Given the service has been initialized with passphrase "passphrase" and is now locked
    When I unlock with passphrase "wrong"
    Then the merged status says "Locked · Ready"
    And the last event says "Unlock failed: Incorrect passphrase for the existing database."

  Scenario: Existing database can be reset and replaced from the UI
    Given the service is unlocked with passphrase "passphrase"
    And a vault named "dev" exists
    And a secret "api-key" exists in vault "dev" with value "secret-value"
    And I lock the service from the UI
    When I reset the database with confirmation "RESET" and passphrase "fresh-passphrase" from the UI
    Then the last event says "Database reset. Unlock it with the new passphrase to continue."
    And the page contains text "Database reset successfully. Unlock it with the new passphrase."
    And the page does not contain text "Database is initialized. Unlock it with its passphrase, or reset it to replace all stored data."
    And unlocking with passphrase "passphrase" fails with message "Incorrect passphrase for the existing database."
    And unlocking with passphrase "fresh-passphrase" succeeds in service state

  Scenario: Manual lock returns the service to locked state
    Given the service is unlocked with passphrase "passphrase"
    When I lock the service from the UI
    Then the merged status says "Locked · Ready"
    And the last event says "Service locked."
    And the log contains text "Service locked."

  Scenario: Valid session settings are saved
    Given the service is unlocked with passphrase "passphrase"
    When I save session settings with timeout_enabled "on", timeout_minutes "22", reset_on_read "off"
    Then the last event says "Session settings saved."
    And the timeout input value is "22"

  Scenario: Invalid timeout value is rejected
    When I save session settings with timeout_enabled "on", timeout_minutes "0", reset_on_read "on"
    Then the last event says "Timeout must be at least 1 minute."

  Scenario: Timer expiration auto-locks the UI
    Given the service is unlocked with passphrase "passphrase"
    And the session inactivity timer has expired
    When I open the UI again
    Then the merged status says "Locked · Ready"
    And the page contains text "Auto-lock triggered after inactivity."
