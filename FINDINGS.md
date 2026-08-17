# Flex API findings (cookie-only probes)

Probed with a live `ASP.NET_SessionId` against `https://flexstudent.nu.edu.pk`.
GET only where noted — no withdraw / password / payment POSTs.

## Session / cookie

- Flex uses **server-side** ASP.NET sessions. The cookie value is just the SessionId.
- When registration bounces to `/Login`, the sniper **waits** (does not exit), re-reads the cookie file, and resumes when CourseRegistration works again.
- Logging in on Flex in a browser may revive the **same** SessionId. If Flex issues a **new** id, paste it into the cookie file (no restart).

## `dump` query param

- **Required** for Course Registration (`/Student/CourseRegistration`, `/Student/CourseRegistrationBS`). Without `dump`, Flex redirects to `/Login`.
- Script auto-extracts `dump` from home / page HTML; you do not paste it.
- Register POST uses dump only in the **Referer** (`CourseRegistrationBS?dump=…`).

## Pages that work **without** `dump`

| Path | Notes |
|------|--------|
| `/Student/Challan` | OK with or without dump. Bogus dump ignored. Form → `/Student/ProcessPaymentThroughNIFT` (no dump in action). |
| `/Student/ChangePassword` | No dump in Flex nav. Form → `/Student/ResetPassword`. |
| `/Student/CourseWithdraw` | Nav uses `semid`, not dump. Bogus dump/semid still returns shell. Form → `/Student/CourseWithdraw`. |
| `/Student/RetakeRequest` | Nav uses `semid`. Bogus dump/semid ignored on GET. Form → `/Student/RetakeRequest`. |
| `/Student/TimeTable` | OK without dump. No form. Bogus dump/semid ignored. |

Wrong `dump=AAAA_…` or `semid=99999` on these GETs did **not** force Login and did not appear required in hidden fields.

## Pages that **need** `dump` (Flex puts it in sidebar links)

- `/Student/CourseRegistration` / `CourseRegistrationBS`
- `/Student/CourseFeedback`
- `/Student/GradeReport`
- `/Student/TentativeStudyPlan`
- `/Student/Transcript`

(Also need a fully alive session — half-dead cookie can still open Challan/Withdraw while Registration → Login.)

## Pages that use `semid` (not dump) in nav

- `/Student/CourseWithdraw?semid=…`
- `/Student/GradeChangeRequest?semid=…`
- `/Student/RetakeRequest?semid=…&EvaltypeId=…`
- `/Student/StudentAttendance?semid=…`
- `/Student/StudentMarks?semid=…`

## Sniper mail / behaviour notes

- `DROP to enroll` only when a **first-section elective** is already registered (not for 4 core courses).
- Session loss → `SESSION waiting` (hourly mail) → after revive → `SESSION restored`.
