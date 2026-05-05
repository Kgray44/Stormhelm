# Discord Relay Live Local-Client Test

This test is skipped by default because it can send a real Discord message through the already signed-in local Discord client. It does not use a Discord API user token, self-bot flow, webhook, or bot route.

## Requirements

- Run on Windows.
- Open Discord and sign in before the test.
- The trusted recipient alias must be explicit.
- The message must be harmless and explicit.
- The confirmation value must exactly match the safety phrase below.

Stormhelm's current local route is `local_client_automation`. It can use the Discord desktop/client route, focus/open Discord, try the Discord quick switch, paste the payload with the clipboard, and press Enter. Verification is only available if the local system probe can produce real post-send evidence. Without that evidence, a completed send gesture is reported as `sent_unverified`, not `sent_verified`.

## PowerShell

```powershell
$env:STORMHELM_DISCORD_LIVE_TEST="1"
$env:STORMHELM_DISCORD_LIVE_TEST_RECIPIENT="Baby"
$env:STORMHELM_DISCORD_LIVE_TEST_MESSAGE="Stormhelm live relay smoke test."
$env:STORMHELM_DISCORD_LIVE_TEST_CONFIRM="I_UNDERSTAND_THIS_SENDS_A_REAL_MESSAGE"
$env:PYTHONPATH="C:\Stormhelm\src"
pytest tests/test_discord_relay.py -k live -q -s
```

Unset the variables afterward:

```powershell
Remove-Item Env:\STORMHELM_DISCORD_LIVE_TEST -ErrorAction SilentlyContinue
Remove-Item Env:\STORMHELM_DISCORD_LIVE_TEST_RECIPIENT -ErrorAction SilentlyContinue
Remove-Item Env:\STORMHELM_DISCORD_LIVE_TEST_MESSAGE -ErrorAction SilentlyContinue
Remove-Item Env:\STORMHELM_DISCORD_LIVE_TEST_CONFIRM -ErrorAction SilentlyContinue
```

## Interpreting Results

- `dispatch_unavailable`: Stormhelm could not reach or identify the local Discord automation route.
- `dispatch_blocked`: Stormhelm held the message because approval, target identity, or policy was missing.
- `dispatch_failed`: A concrete local step failed, such as route navigation, clipboard paste, or send gesture.
- `sent_unverified`: Stormhelm performed the final send gesture in Discord but did not verify the message appeared.
- `sent_verified`: Stormhelm observed real post-send evidence that the message appeared in the target thread.

The test prints step results including focus, Discord surface identification, DM navigation, message input location, payload insertion, send gesture, and message-visible verification. `sent_verified` must include real verification evidence; input clearing or pressing Enter alone is not enough.
