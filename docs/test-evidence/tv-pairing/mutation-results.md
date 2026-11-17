| accept I/L/O/U | caught by TestCallbackData, TestStartPayload |
| payload case-sensitive | caught by TestStartHandler, TestStartPayload, TestStartText |
| code not upper-cased | caught by TestStartHandler, TestStartPayload, TestStartText |
| callback code not validated | caught by TestCallbackData, TestConfirmHandler |
| display without dash | caught by TestCallbackData, TestConfirmHandler, TestStartHandler |
| full code logged | caught by TestCallbackData |
| 409 shown as success | caught by TestConfirmHandler |
| 422 does not open plans | caught by TestConfirmHandler |
| 422 drops the retry button | caught by TestConfirmHandler |
| claims for a fixed id | caught by TestConfirmHandler |
| 422 not mapped | caught by TestClaimClient |
| wrong path | caught by TestClaimClient |
| wrong body field | caught by TestClaimClient |
| expected answers logged as errors | caught by TestClaimClient |
| start handler never matches (unit tests do not route; e2e does) | NOT CAUGHT |
| anti-phishing sentence dropped | caught by TestCopy |
| start handler never matches | caught by the e2e: tests/e2e/test_tv_pair_e2e.py -k paid_user_pairs -> 1 failed (run by hand) |
