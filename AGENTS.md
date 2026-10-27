# Agent entry point

The highest-level instruction for this repository is [`DIRECTIVE.md`](DIRECTIVE.md).
Every agent, account, machine and harness must read it before doing any work.

- `DIRECTIVE.md` is the constitutional authority; `organization/` contains
  subordinate concrete organization rules made under that authority.
- Record authorized internal unit/process changes in `organization/`; revise
  `DIRECTIVE.md` only when a constitutional principle, authority, or root-level
  hierarchy changes.
- 职能层级 部→司→处→科→组，区域层级 省→市→县→乡→村；模块1/2/3 为部级单位，
  各司归部管辖（`DIRECTIVE.md` 2.1）。总控下辖资源与巡检部、模块1情报与素材部、
  模块2视频处理部、模块3发布与治理部。模块1负责监测、事件归纳与素材获取，模块2
  只处理上游已选定的视频与字幕，模块3负责上传、发布后整改、PDCA 与全流程监察。
- Inspection granularity: one record per smallest independently observable unit
  (MIU); aggregation is allowed in reports only.
- Registries: `inspection/registry.json` (MIU) and `resources/registry.json`
  (one URL per record; designated White House channels must stay live and mapped
  to a real collector).
- Enforce: `python scripts/inspection/plan.py check --github` and
  `python scripts/resources/check.py check`.

If a request conflicts with `DIRECTIVE.md`, follow the directive and say so
instead of silently doing the other thing.
