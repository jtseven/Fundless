from pathlib import Path
from typing import Sequence

import pandas as pd
from pydantic import TypeAdapter
from sqlmodel import Session, create_engine, select

from fundless.models import Trade, TradeCreate

sqlite_file_name = "database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

engine = create_engine(sqlite_url, echo=True)


def trades_from_csv(csv_file: Path) -> list[Trade]:
    trades_from_file = pd.read_csv(csv_file)
    trades_dict = trades_from_file.to_dict(orient="records")
    adapter = TypeAdapter(list[Trade])
    trades = adapter.validate_python(trades_dict)
    with Session(engine) as session:
        session.add_all(trades)
        session.commit()
    return trades


def get_trades() -> Sequence[Trade]:
    with Session(engine) as session:
        trades = session.exec(select(Trade)).all()
    return trades


def add_trade(trade: TradeCreate) -> Trade:
    with Session(engine) as session:
        db_trade = Trade.model_validate(trade)
        session.add(db_trade)
        session.commit()
        session.refresh(db_trade)
    return db_trade


def trades_as_df(set_index: bool = True) -> pd.DataFrame:
    """Get all trades from DB as Pandas DataFrame.
    Usage
    ----------
    df = trades_as_df()
    Parameters
    ----------
    :param set_index: bool: Sets the first column, usually the primary key, to dataframe index."""
    trades = get_trades()
    records = [obj.model_dump() for obj in trades]
    columns = list(trades[0].model_json_schema()["properties"].keys())
    df = pd.DataFrame.from_records(records, columns=columns)
    return df.set_index(columns[0]) if set_index else df
