from sqlalchemy import create_mock_engine

from packages.downstream_claims_connector import SqlAlchemyFinalizedClaimsConnector


def test_connector_accepts_mysql_engine_and_safe_table_name():
    engine = create_mock_engine("mysql+pymysql://", lambda *_args, **_kwargs: None)
    connector = SqlAlchemyFinalizedClaimsConnector(
        engine, table="finalized_claim_fields", source_system="claims",
    )
    assert connector.engine.dialect.name == "mysql"


def test_connector_rejects_injected_table_name():
    engine = create_mock_engine("mysql+pymysql://", lambda *_args, **_kwargs: None)
    try:
        SqlAlchemyFinalizedClaimsConnector(engine, table="claims; DROP TABLE claims", source_system="x")
    except ValueError:
        pass
    else:
        raise AssertionError("unsafe table identifier accepted")
