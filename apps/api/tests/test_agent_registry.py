from emporia_api.agents.registry import get_agent, list_agents


def test_fifteen_specialists_have_complete_advisory_execution_contracts():
    agents = list_agents()
    assert len(agents) == 15
    assert len({agent.id for agent in agents}) == 15
    assert {
        "catalogue-data-architect",
        "inventory-replenishment-planner",
        "fulfilment-logistics-analyst",
        "commerce-finance-controller",
        "marketplace-policy-compliance-analyst",
        "customer-support-operations-specialist",
        "commerce-analytics-experimentation-analyst",
    }.issubset({agent.id for agent in agents})

    for agent in agents:
        assert get_agent(agent.id) is agent
        assert agent.version
        assert len(agent.mission) > 30
        assert agent.expertise
        assert agent.deliverables
        assert agent.required_context
        assert len(agent.system_prompt) > 800
        assert "Never fabricate" in agent.system_prompt
        assert "has no action tools enabled" in agent.system_prompt
