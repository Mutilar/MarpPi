# Project Architecture Overview

<!-- mermaid-output: assets/diagrams/project-architecture.png -->
```mermaid
flowchart TB
	User((End User))
	Mic["Mic"]
	Speaker["Speaker"]

	subgraph Frontend["Tauri"]
		subgraph TypeScript["TypeScript"]
			UI["UI Components"]
		end
	end

	subgraph Python["Python"]
		AudioIn["Audio Pipeline"]
		VOCA["VOCA"]
		Pipecat["Pipecat"]
		STT["STT"]
		TTS["TTS"]
		LangChain["LangChain"]
		StateManager["State Manager"]
	end

	subgraph FoundryGroup["Foundry"]
		FoundryLLM["Local LLM"]
	end

	subgraph PerceptiveGroup["Perceptive Shell"]
		Perceptive["Local LLM"]
	end

	subgraph SQLGroup["SQL"]
		SQLDB["Persistence"]
	end

	classDef actor fill:#fde2e2,stroke:#c0392b,color:#2c3e50;
	classDef io fill:#e8f8f5,stroke:#1e8449,color:#145a32;
	classDef ui fill:#eaf2f8,stroke:#2874a6,color:#154360;
	classDef python fill:#fcf3cf,stroke:#b7950b,color:#7d6608;
	classDef rust fill:#fdebd0,stroke:#d35400,color:#6e2c00;
	classDef service fill:#f6ddcc,stroke:#af601a,color:#4d2600;
	classDef remote fill:#f5eef8,stroke:#8e44ad,color:#512e5f;

	User -->|Interactions| UI
	Mic -->|Audio| AudioIn
	AudioIn -->|Audio| VOCA
	VOCA -->|Audio| Pipecat
	UI -->|Prompt| Pipecat
	StateManager -->|Data| UI
	Pipecat -->|Audio| STT
	STT -->|Text| Pipecat
	Pipecat -->|Text| TTS
	TTS -->|Audio| Pipecat
	Pipecat -->|Audio| Speaker
	Speaker -->|Audio| User
	Pipecat -->|Data| StateManager
	StateManager -->|Data| SQLDB
	SQLDB -->|Data| StateManager
	Pipecat -->|Text| LangChain
	LangChain -->|Text| FoundryLLM
	FoundryLLM -->|Text| LangChain
	LangChain -->|Data| Perceptive
	Perceptive -->|Data| LangChain
	LangChain -->|Text| Pipecat

	class User actor
	class Mic,Speaker io
	class UI ui
	class AudioIn,VOCA,Pipecat,STT,TTS,LangChain,StateManager python
	class FoundryLLM,SQLDB service
	class Perceptive service
```

### Notes
- The Electron/Tauri shell hosts the TypeScript webview UI and exchanges events with the Python core over localhost APIs.
- Python core services handle voice-first interaction (Pipefect), chat orchestration, audio capture/playback, and coordinate LLM workflows.
- Foundry Local and SQL are co-located services accessed over localhost, while PSARI provides remote image-generation capabilities.
- Microphone input and audio playback integrate directly with the Python runtime, enabling round-trip conversational experiences.

## Cost-Benefit Scenario: Tauri-Only Stack

<!-- mermaid-output: assets/diagrams/tauri-only-architecture.png -->
```mermaid
flowchart TB
	User((End User))
	Mic["Mic"]
	Speaker["Speaker"]

	subgraph Tauri["Tauri"]
		subgraph Rust["Rust"]
			AudioIn["Audio Pipeline"]
			VOCA["VOCA"]
			STT["STT"]
			TTS["TTS"]
			LangChain["LangChain"]
		end
		subgraph TypeScript["TypeScript"]
			UI["UI Components"]
			Pipecat["Pipecat"]
			StateManager["State Manager"]
		end
	end

	subgraph FoundryGroup["Foundry"]
		FoundryLLM["Local LLM"]
	end

	subgraph PerceptiveGroup["Perceptive Shell"]
		Perceptive["Local LLM"]
	end

	subgraph SQLGroup["SQL"]
		SQLDB["Persistence"]
	end

	classDef actor fill:#fde2e2,stroke:#c0392b,color:#2c3e50;
	classDef io fill:#e8f8f5,stroke:#1e8449,color:#145a32;
	classDef ui fill:#eaf2f8,stroke:#2874a6,color:#154360;
	classDef python fill:#fcf3cf,stroke:#b7950b,color:#7d6608;
	classDef rust fill:#fdebd0,stroke:#d35400,color:#6e2c00;
	classDef service fill:#f6ddcc,stroke:#af601a,color:#4d2600;
	classDef remote fill:#f5eef8,stroke:#8e44ad,color:#512e5f;

	User -->|Interactions| UI
	Mic -->|Audio| AudioIn
	AudioIn -->|Audio| VOCA
	VOCA -->|Audio| Pipecat
	UI -->|Prompt| Pipecat
	Pipecat -->|Audio| STT
	STT -->|Text| Pipecat
	Pipecat -->|Text| LangChain
	LangChain -->|Text| FoundryLLM
	FoundryLLM -->|Text| LangChain
	LangChain -->|Text| Pipecat
	LangChain -->|Data| Perceptive
	Perceptive -->|Data| LangChain
	Pipecat -->|Text| TTS
	TTS -->|Audio| Pipecat
	Pipecat -->|Audio| Speaker
	Speaker -->|Audio| User
	Pipecat -->|Data| StateManager
	StateManager -->|Data| SQLDB
	StateManager -->|Data| UI
	SQLDB -->|Data| StateManager

	class User actor
	class Mic,Speaker io
	class UI,Pipecat,StateManager ui
	class AudioIn,VOCA,STT,TTS,LangChain rust
	class FoundryLLM,SQLDB service
	class Perceptive service
```

### Highlights
- **Pipecat-mediated playback:** TTS responses now flow back into Pipecat for orchestration before audio reaches the speaker, keeping UI state and playback tightly synchronized.

### Trade-offs
- **Benefit:** Eliminates cross-process communication; all voice, UI, and orchestration live inside the Tauri process, reducing deployment overhead.
- **Benefit:** Direct Rust control over audio and LLM calls can simplify resource sharing and caching.
- **Cost:** Rust layer must host STT/TTS and LangChain integrations, increasing complexity and maintenance burden inside the client runtime.
- **Cost:** Tight coupling of Pipecat, audio services, and persistence reduces flexibility for scaling or swapping components independently.

## Alternate Flow: VOCA-First STT Handoff

<!-- mermaid-output: assets/diagrams/tauri-alternate-flow.png -->
```mermaid
flowchart TB
	User((End User))
	Mic["Mic"]
	Speaker["Speaker"]

	subgraph Tauri["Tauri"]
		subgraph Rust["Rust"]
			AudioIn["Audio Pipeline"]
			VOCA["VOCA"]
			STT["STT"]
			TTS["TTS"]
			LangChain["LangChain"]
		end
		subgraph TypeScript["TypeScript"]
			UI["UI Components"]
			Pipecat["Pipecat"]
			StateManager["State Manager"]
		end
	end

	subgraph FoundryGroup["Foundry"]
		FoundryLLM["Local LLM"]
	end
	subgraph PerceptiveGroup["Perceptive Shell"]
		Perceptive["Local LLM"]
	end

	subgraph SQLGroup["SQL"]
		SQLDB["Persistence"]
	end

	classDef actor fill:#fde2e2,stroke:#c0392b,color:#2c3e50;
	classDef io fill:#e8f8f5,stroke:#1e8449,color:#145a32;
	classDef ui fill:#eaf2f8,stroke:#2874a6,color:#154360;
	classDef python fill:#fcf3cf,stroke:#b7950b,color:#7d6608;
	classDef rust fill:#fdebd0,stroke:#d35400,color:#6e2c00;
	classDef service fill:#f6ddcc,stroke:#af601a,color:#4d2600;
	classDef remote fill:#f5eef8,stroke:#8e44ad,color:#512e5f;

	User -->|Interactions| UI
	Mic -->|Audio| AudioIn
	AudioIn -->|Audio| VOCA
	VOCA -->|Audio| STT
	STT -->|Text| Pipecat
	UI -->|Prompt| Pipecat
	Pipecat -->|Text| LangChain
	LangChain -->|Text| FoundryLLM
	FoundryLLM -->|Text| LangChain
	LangChain -->|Data| Perceptive
	Perceptive -->|Data| LangChain
	LangChain -->|Text| Pipecat
	Pipecat -->|Text| TTS
	TTS -->|Audio| Speaker
	Speaker -->|Audio| User
	Pipecat -->|Data| StateManager
	StateManager -->|Data| SQLDB
	StateManager -->|Data| UI
	SQLDB -->|Data| StateManager

	class User actor
	class Mic,Speaker io
	class UI,Pipecat,StateManager ui
	class AudioIn,VOCA,STT,TTS,LangChain rust
	class FoundryLLM,SQLDB service
	class Perceptive service
```

### Highlights
- **Streamlined STT handoff:** VOCA now delivers processed audio frames directly to STT, reducing round-trips between the Pipecat instance and the Rust core for speech recognition requests.
- **Pipecat consumes transcripts:** Pipecat receives finalized transcripts from STT rather than initiating the request, emphasizing a callback-driven flow from the Rust services into the UI orchestrator.
