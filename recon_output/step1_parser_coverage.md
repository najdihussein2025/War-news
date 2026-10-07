# Step 1d parser coverage

| metric | current DB | aliases simulated |
|---|---:|---:|
| bulletins complete | 48 | 63 |
| bulletins partial | 166 | 151 |
| bulletins residual_only | 7 | 7 |
| **resolved items / all item candidates** | 3697/4796 | 3790/4618 |
| residual entries total, by kind | 1099: {'leftover_token': 481, 'unresolved_place': 239, 'out_of_scope': 374, 'unresolved_header': 5} | 828 |
| residual entries per bulletin (median, p90) | 3, 10 | — |
| timeline events with exact time | 36 | 36 |

- S4 workload: 116 bulletins have a place-like residual under an approved header.

## Top residual texts by kind

- `leftover_token` / `عيتا`: 36
- `leftover_token` / `الجبل`: 36
- `unresolved_place` / `عيتا الجبل`: 25
- `leftover_token` / `حلتا`: 18
- `leftover_token` / `وادي`: 18
- `leftover_token` / `الطيبه`: 16
- `leftover_token` / `بسطره`: 14
- `leftover_token` / `بين`: 13
- `leftover_token` / `الشقيف`: 13
- `leftover_token` / `سدانه`: 12
- `unresolved_place` / `الطيبه`: 11
- `unresolved_place` / `حلتا`: 10
- `leftover_token` / `القصير`: 10
- `unresolved_place` / `القصير`: 10
- `leftover_token` / `علمان`: 10
- `leftover_token` / `الشومريه`: 10
- `unresolved_place` / `علمان الشومريه`: 10
- `leftover_token` / `مزرعه`: 9
- `unresolved_place` / `مزرعه بسطره عند اطراف كفرشوبا`: 9
- `leftover_token` / `مظلم-بيت`: 9

## Remaining blockers by class

- leftover tokens: 138
- unresolved places: 116
- prose/timeline: 82
- unresolved headers: 2

## Window rules

- explicit_date: 98
- overnight:end_time_ignored: 45
- default: 41
- overnight: 18
- default:end_time_ignored: 13
- explicit_date:stale_suspect: 4
- explicit_date:future_ignored: 1
- broad_partial:end_time_ignored: 1

## Top leftover tokens

- `عيتا`: 41
- `الجبل`: 41
- `حلتا`: 28
- `بسطره`: 23
- `مزرعه`: 18
- `وادي`: 18
- `الطيبه`: 16
- `الشقيف`: 16
- `بين`: 13
- `سدانه`: 12
- `القصير`: 10
- `علمان`: 10
- `الشومريه`: 10
- `مظلم-بيت`: 9
- `ليف`: 9
- `منطقه`: 9
- `كفرمان`: 9
- `صريين`: 8
- `صوتيه`: 8
- `دوحه`: 8
- `احراق`: 6
- `شقه`: 6
- `سكنيه`: 6
- `محلقات`: 6
- `الخردله`: 5
- `قنابل`: 5
- `الدير-النبطيه`: 5
- `الفوقا`: 5
- `واطراف`: 5
- `دوبيه`: 5

## Top unresolved places

- `عيتا الجبل`: 25
- `الطيبه`: 11
- `حلتا`: 10
- `القصير`: 10
- `علمان الشومريه`: 10
- `مزرعه بسطره عند اطراف كفرشوبا`: 9
- `وادي مظلم-بيت ليف`: 9
- `صريين`: 8
- `سدانه عند اطراف الهباريه`: 8
- `اطراف عيتا الجبل`: 8
- `دوحه كفرمان`: 8
- `مرتفعات حلتا`: 8
- `حرش عيتا الجبل`: 8
- `محلقات`: 6
- `مجري نهر الخردله`: 5
- `حي الدير-النبطيه الفوقا`: 5
- `مرتفعات حلتا بقذيفتين`: 5
- `الطيبه لجهه دير سريان`: 5
- `بسطره`: 5
- `حانين`: 5
- `السدانه-كفرشوبا`: 5
- `بين القنطره-الطيبه`: 5
- `علي الطاهر+فوسفوري`: 4
- `سدانه`: 4
- `وادي الخنازير-القصير`: 4
- `عبترون`: 4
- `حي الرويس-النبطيه`: 3
- `الريحان`: 3
- `جبل السويداء-كفررمان`: 3
- `احراق منازل`: 3

## Unresolved headers

- `الغارات من الطيران الحربي التي استهدفت عده مناطق في الجنوب`: 1
- `عمليات التفجير التي قام بها العدو و قد طالت بلدات`: 1
- `القصف المدفعي و قد طال المناطق التاليه`: 1
- `عمليات التمشيط التي قام بها العدو وقد طالت بلدات`: 1
- `باخلاء مبني عند اطراف البلده و قام بعد ذلك بتدميره، اضافه الي غارات اخري استهدفت بلده النبطيه الفوقا`: 1
