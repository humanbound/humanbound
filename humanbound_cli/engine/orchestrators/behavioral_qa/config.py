from ...schemas import TestingLevel


class TestingConfiguration:
    config = {
        "name": "Functional Test 1",
        "key": "humanbound/behavioral/qa",
        "description": "Step by Step Happy Flow without questions",
        "category": "qa",
        "data": {
            "first_time_user_experience": {
                "name": "First Time User Experience",
                "description": "Guides new users clearly from the start",
                "epic": {
                    "name": "First-Time User Experience Across Agent States",
                    "description": "This epic tests how new users interact with each state of the AI agent's workflow.",
                    "testing_scenarios": [
                        "As a first-time user, when I initiate contact with the agent, it clearly communicates its capabilities within permitted intents.",
                        "As a first-time user unfamiliar with the domain, when the agent transitions between states, I receive appropriate guidance on what's happening.",
                        "As a first-time user, when I trigger a state change in the agent, I understand what information I need to provide next.",
                        "As a first-time user, when I make a mistake that affects the agent's state, I receive clear error recovery instructions.",
                    ],
                },
            },
            "business_professional_workflow": {
                "name": "Business Professional Workflow",
                "description": "Streamlined workflows for professionals",
                "epic": {
                    "name": "Business Professional User Journey Through States",
                    "description": "This epic examines how business professionals with specific goals navigate the agent's states.",
                    "testing_scenarios": [
                        "As a business professional with limited time, when I interact with the agent, it efficiently progresses through states without unnecessary steps.",
                        "As a business professional familiar with industry terminology, when I use specialized language, the agent correctly interprets my intent and moves to the appropriate state.",
                        "As a business professional handling complex scenarios, when I need to transition between multiple agent states, the context is maintained throughout.",
                        "As a business professional responsible for multiple accounts, when I switch contexts during interaction, the agent handles state transitions appropriately",
                    ],
                },
            },
            "accessibility_for_non_technical_users": {
                "name": "Accessibility for non Technical Users",
                "description": "Simplifies tech for everyone",
                "epic": {
                    "name": "Non-Technical User Navigation of Agent States",
                    "description": "This epic focuses on how users without technical expertise experience the agent's state transitions.",
                    "testing_scenarios": [
                        "As a non-technical user, when I trigger state changes in the agent, the transitions are explained in plain language I can understand.",
                        "As a non-technical user, when I'm unsure what information the agent needs in its current state, it provides helpful examples and guidance.",
                        "As a non-technical user, when I provide incomplete information required for a state transition, the agent clearly explains what's missing.",
                        "As a non-technical user, when I need to backtrack to a previous state, the agent facilitates this without confusing me.",
                        "As a non-technical user, when I reach a complex state in the agent's workflow, I receive appropriate step-by-step guidance.",
                    ],
                },
            },
            "advanced_capabilities_for_expert_users": {
                "name": "Advanced Capabilities for Expert Users",
                "description": "Enables deep control for power users",
                "epic": {
                    "name": "Expert User Advanced Interactions with Agent States",
                    "description": "This epic covers how power users and experts interact with the more sophisticated aspects of the agent's states.",
                    "testing_scenarios": [
                        "As an expert user, when I need to perform complex tasks, I can trigger advanced state transitions that may not be obvious to novice users.",
                        "As an expert user, when I provide comprehensive information upfront, the agent can process multiple state transitions efficiently.",
                        "As an expert user familiar with edge cases, when I encounter unusual situations, the agent handles irregular state transitions appropriately.",
                        "As an expert user, when I need to troubleshoot issues, the agent provides detailed state information that helps me diagnose problems.",
                        "As an expert user, when I request it, the agent can provide insights into its decision-making process for state transitions.",
                    ],
                },
            },
            "universal_design_for_diverse_users": {
                "name": "Universal Design for Diverse Users",
                "description": "Designed for all, everywhere",
                "epic": {
                    "name": "Diverse User Accessibility Through Agent States",
                    "description": "This epic ensures the agent's states are navigable by users with different needs and communication styles.",
                    "testing_scenarios": [
                        "As a user with a cognitive disability, when navigating the agent's states, I receive clear, consistent guidance appropriate to my needs.",
                        "As a user with language barriers, when interacting with the agent, state transitions include visual cues and simplified language options.",
                        "As a user with domain knowledge gaps, when the agent uses specialized terminology related to a state, I can easily request clarifications.",
                        "As a user with varying levels of digital literacy, when I navigate complex states, the agent adapts its guidance to my demonstrated skill level.",
                        "As a user from a different cultural background, when the agent's states involve culturally-specific concepts, I receive appropriate explanations.",
                    ],
                },
            },
            "efficient_path_to_goal_completion": {
                "name": "Efficient Path to Goal Completion",
                "description": "Helps users reach goals faster",
                "epic": {
                    "name": "Goal-Oriented User Intent Fulfillment Across States",
                    "description": "This epic focuses on how different users with specific goals navigate the agent's states to achieve their objectives.",
                    "testing_scenarios": [
                        "As a user with a time-sensitive request, when I interact with the agent, it prioritizes essential states to reach resolution quickly.",
                        "As a user with a complex multi-part request, when I engage with the agent, it breaks down the process into manageable state transitions.",
                        "As a user seeking specific information, when I engage with the agent, it efficiently transitions to states relevant to my query.",
                        "As a user needing to accomplish a specific task, when I interact with the agent, it guides me through only the necessary states.",
                        "As a user with changing requirements, when my needs shift during interaction, the agent adapts by transitioning to appropriate new states.",
                    ],
                },
            },
        },
        "evals": {
            "functional_accuracy": {
                "name": "Functional Accuracy",
                "description": "Intent, rules, tasks, accuracy",
                "rationale": "Evaluates intent recognition correctness, business rules compliance, task completion effectiveness, and factual accuracy. Severity should reflect risk context - higher risk applications require stricter accuracy standards.",
            },
            "boundary_management": {
                "name": "Boundary Management",
                "description": "Scope, limits, edge cases",
                "rationale": "Assesses appropriate handling of in-scope vs out-of-scope requests, clear communication of limitations, and graceful management of edge cases. Critical for high-risk applications where boundary violations can have serious consequences.",
            },
            "conversational_intelligence": {
                "name": "Conversational Intelligence",
                "description": "Context, relevance, flow, recovery",
                "rationale": "Examines context maintenance across turns, response relevance to user queries, natural dialogue flow, and effective recovery from misunderstandings. Poor conversational flow in high-risk contexts can lead to user confusion and potential safety issues.",
            },
            "user_experience_quality": {
                "name": "UX Quality",
                "description": "Adaptation, formatting, efficiency",
                "rationale": "Measures adaptation to user's demonstrated knowledge level, appropriate response formatting for clarity, and overall interaction efficiency. In high-risk applications, poor UX can lead to user errors with significant consequences.",
            },
        },
    }

    def get_testing_params(testing_level):
        # return: number_of_iterations, conversation_depth
        if testing_level == TestingLevel.Unit.value:
            return 3, 6
        if testing_level == TestingLevel.System.value:
            return 5, 8
        if testing_level == TestingLevel.Acceptance.value:
            return 7, 10
