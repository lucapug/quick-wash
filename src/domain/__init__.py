"""Domain model: one venue, three machine types, the machine.

quick-wash is a single laundromat, so no domain object carries a venue identifier and there is no
multi-site abstraction (docs/spec.md, Domain model).

Tariff and cycle duration belong to the **type**, never to the individual machine row: a machine
row stores `id`, `code`, `type`, `state`, `changed_at` and nothing about price or duration.
Per-machine pricing was explicitly rejected, so `cycle_minutes` and `tokens_required` are answered
through the type registry — the same type always answers the same.

The numbers themselves are seed data in src/config.py; this module is the shape that reads them.

The package holds the time half of the domain as a submodule: `src/domain/time.py` is the pure
helper for valid start times, the refusal vocabulary and the next valid alternatives (R1, R2).
"""

from dataclasses import dataclass

from src.config import SEED

# A machine row holds no price field and no duration field, and no venue identifier.
MACHINE_FIELDS = ("id", "code", "type", "state", "changed_at")


@dataclass(frozen=True)
class MachineType:
    key: str
    capacity_kg: int | None
    cycle_minutes: int
    tokens_required: int

    def tariff(self) -> dict:
        return {"capacity_kg": self.capacity_kg, "cycle_minutes": self.cycle_minutes,
                "tokens": self.tokens_required}


def types(config: dict = SEED) -> dict[str, MachineType]:
    """The three types of the seed inventory, read from the configuration."""
    return {key: MachineType(key, tariff["capacity_kg"], tariff["cycle_minutes"], tariff["tokens"])
            for key, tariff in config["tariffs"].items()}


def tariff_of(type_key: str, config: dict = SEED) -> MachineType | None:
    return types(config).get(type_key)


@dataclass
class Machine:
    """A physical machine: it says which type it is, and inherits everything else from that type."""

    id: int
    code: str
    type: str
    state: str
    changed_at: str

    def tariff(self, config: dict = SEED) -> MachineType:
        """The machine has no price of its own: the type answers (R1, Domain model)."""
        found = tariff_of(self.type, config)
        if found is None:
            raise KeyError(f"unknown machine type: {self.type}")
        return found

    def view(self, config: dict = SEED) -> dict:
        tariff = self.tariff(config)
        return {
            "id": self.id,
            "code": self.code,
            "type": self.type,
            "capacity_kg": tariff.capacity_kg,
            "cycle_minutes": tariff.cycle_minutes,
            "tokens_required": tariff.tokens_required,
            "state": self.state,
        }


def machine_view(row: dict, config: dict = SEED) -> dict:
    """Read a machine row through the domain object: only the stored fields are the machine's own."""
    machine = Machine(**{field: row[field] for field in MACHINE_FIELDS})
    return machine.view(config)


def seed_view(counts: dict | None = None, config: dict = SEED) -> dict:
    """The seed numbers verbatim, so a reviewer can read them over HTTP without reading code."""
    registry = types(config)
    inventory = counts or config["types"]
    return {
        "machines": sum(inventory.values()),
        "types": dict(inventory),
        "cycle_minutes": {key: tariff.cycle_minutes for key, tariff in registry.items()},
        "tokens_required": {key: tariff.tokens_required for key, tariff in registry.items()},
        "turnover_buffer_minutes": config["turnover_buffer_minutes"],
        "cleaning_buffer_minutes": config["cleaning_buffer_minutes"],
        "grid_minutes": config["grid_minutes"],
        "opening_hours": config["opening_hours"],
        "closed_days": config["closed_days"],
    }
