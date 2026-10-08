from bank_statement_assistant.adapters.mcp.server import McpServices, create_server


class UnusedTransactions:
    def list(self, *, filters):
        raise AssertionError("not called")

    def get(self, transaction_id):
        raise AssertionError("not called")

    def history(self, transaction_id):
        raise AssertionError("not called")


class UnusedStatements:
    def get(self, statement_id):
        raise AssertionError("not called")


class UnusedReporting:
    def report(self, query):
        raise AssertionError("not called")


class UnusedProposals:
    def create(self, **kwargs):
        raise AssertionError("not called")


def test_mcp_server_exposes_allowlisted_financial_tools() -> None:
    server = create_server(
        McpServices(
            transactions=UnusedTransactions(),
            statements=UnusedStatements(),
            reporting=UnusedReporting(),
            proposals=UnusedProposals(),
        )
    )

    assert set(server._tool_manager._tools) == {
        "search_transactions",
        "get_monthly_report",
        "get_statement_review",
        "get_classification_details",
        "propose_correction",
    }
    assert server._tool_manager.get_tool("search_transactions").annotations.readOnlyHint is True
    assert server._tool_manager.get_tool("propose_correction").annotations.destructiveHint is False


def test_search_transactions_rejects_unbounded_pages() -> None:
    server = create_server(
        McpServices(
            transactions=UnusedTransactions(),
            statements=UnusedStatements(),
            reporting=UnusedReporting(),
            proposals=UnusedProposals(),
        )
    )
    tool = server._tool_manager.get_tool("search_transactions")

    try:
        tool.fn(limit=51)
    except ValueError as exc:
        assert str(exc) == "limit must be between 1 and 50"
    else:
        raise AssertionError("unbounded page was accepted")


def test_monthly_report_requires_a_bounded_month_period() -> None:
    server = create_server(
        McpServices(
            transactions=UnusedTransactions(),
            statements=UnusedStatements(),
            reporting=UnusedReporting(),
            proposals=UnusedProposals(),
        )
    )
    tool = server._tool_manager.get_tool("get_monthly_report")

    try:
        tool.fn(month_from="2024-01", month_to="2027-01")
    except ValueError as exc:
        assert str(exc) == "report period must span between 0 and 24 months"
    else:
        raise AssertionError("unbounded report period was accepted")
