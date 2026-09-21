---
name: systems-map
description: Explain or record where work happens across repositories, boards, documents, agents, and runtimes, including each system's purpose, authority, access route, and related tasks. Use when the user asks which systems are in use, where a task lives, or to register a work system.
---

# Systems Map

Help the user find the place where work is performed and the source that owns its status.

Read [the shared work-record contract](../checkpoint/references/work-records.md). Use the existing systems map and known project links. Default to the current project; broader requests may follow explicitly supplied or registered projects within the same business identity. This is an inventory of work locations, not a scan of installed software, accounts, or unrelated home directories.

## Inspect or record

- For “where,” “which systems,” or a bare invocation, produce a read-only map. Check relevant registered sources through available read-only tools and show coverage gaps. If no registry exists, build a provisional view from available project context without creating files.
- For “register,” “record,” “update,” or “save this map,” persist the requested changes to the existing systems map using [checkpoint](../checkpoint/SKILL.md). Match existing entries by location and purpose; retain IDs and task relationships. Capture only actual or explicitly registered systems.
- If a system moved or was retired, retain the old reference with its disposition and replacement when known. Lack of access is not proof of retirement. Do not silently switch task authority because a new board or mirror exists.

## Make relationships clear

For each relevant system, identify its purpose, project, direct location, authoritative information, access route, related work IDs, and last observation. Explain mirrors and dependencies when they matter: for example, an issue owns task status while a board displays it and a runtime attempts execution.

Use a compact table for simple inventories. Use a small diagram only when relationships would otherwise be hard to follow. An unknown link or access route stays unknown; never invent one.

Distinguish configured, reachable, and currently active. Check process state only when needed and with available read-only evidence. An old heartbeat or session reference proves only a past observation. Preserve its timestamp when it cannot be refreshed.

## Finish at the work location

Tell the user which system to open for the requested task, what to do there, and how to recognize success. Link saved map changes if requested. If a source is inaccessible, say what remains unknown and the smallest useful next step.

This workflow does not install integrations, obtain credentials, launch or stop agents, migrate work, or change external systems merely by recording their existence. Store no secret values. Follow the user's separately authorized actions without adding redundant approval requests.
