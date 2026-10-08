# Previously deleted summary rows without a recorded reason

Read-only query against `war_news_dev`; PostgreSQL returned
`transaction_read_only=on`.  This covers the 174 rows marked `soft_deleted=True`
by the summary audit that have `deleted_reason IS NULL` and no delete audit row.

| UTC hour | rows | time range (UTC) | source channels | likely source |
|---|---:|---|---|---|
| 2026-08-26 06 | 11 | 06:53:42–06:53:43 | mehwaralmokawma, nabatiehchannel, sameralhajali | predates all named scripts; unknown legacy path |
| 2026-08-28 07 | 6 | 07:24:57–07:27:44 | alichoeib1970, mehwaralmokawma | predates all named scripts; unknown legacy path |
| 2026-09-02 08 | 4 | 08:29:35 | hashemsayed | predates Sep 17/24 and Oct 5 scripts; unknown legacy path |
| 2026-09-02 09 | 76 | 09:00:24–09:31:02 | alichoeib1970, hashemsayed, Janoubana, mehwaralmokawma, nabatiehchannel, sameralhajali | same historical bulk run; no matching committed script |
| 2026-09-02 10 | 35 | 10:45:27–10:50:32 | alichoeib1970, hashemsayed, mehwaralmokawma, nabatiehchannel, sameralhajali | same historical bulk run; no matching committed script |
| 2026-09-07 12 | 1 | 12:17:37 | Janoubana | unknown legacy path |
| 2026-09-09 10 | 18 | 10:10:29–10:10:32 | alichoeib1970, Janoubana, nabatiehchannel, sameralhajali | unknown legacy path |
| 2026-09-09 11 | 1 | 11:01:43 | nabatiehchannel | unknown legacy path |
| 2026-09-22 04 | 5 | 04:52:29 | mehwaralmokawma | does not match the Sep 17 script date; unknown legacy path |
| 2026-09-23 09 | 5 | 09:12:05 | alichoeib1970 | does not match the Sep 24 script date; unknown legacy path |
| 2026-10-01 04/11/12 | 12 | 04:50:59–12:01:11 | alichoeib1970 | predates the Oct 5 script; unknown legacy path |

The named scripts were introduced/changed on Aug 17, Sep 17, Sep 24, and Oct 5,
but none of their committed dates aligns with a cluster conclusively. The large
Sep 2 bulk cluster is the strongest evidence of an older untracked/manual
rematerialization or direct database operation. No data was changed.
