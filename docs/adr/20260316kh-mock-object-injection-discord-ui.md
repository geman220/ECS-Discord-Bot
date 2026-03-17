# ADR: 20260316kh - Mock-Object Injection for Discord UI

## Status
Accepted

## Context
When testing Discord Modals, initial attempts to assign values to input fields (e.g., `modal.home_score.value = "2"`) failed with `AttributeError: can't set attribute`. This is because `discord.ui.TextInput.value` is a read-only property in the `discord.py` library.

## Decision
Instead of assigning to the `.value` property, the test suite now mocks the entire `TextInput` object within the Modal. By injecting a `MagicMock` where the `TextInput` would normally be, we can control the `.value` returned during the `on_submit` callback.

## Consequences
- **Pros**: Reliably tests Modal submission logic without library conflicts. Avoids complex monkeypatching of library internals.
- **Cons**: Tests are slightly more decoupled from the actual `discord.ui` implementation details.
- **Maintenance**: Future UI tests should follow this "Mock Injection" pattern rather than property assignment.
