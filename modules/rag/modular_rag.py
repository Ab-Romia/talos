"""
Modular RAG System

A flexible RAG system implementing the Modular RAG framework with
configurable pre-retrieval, retrieval, and orchestration components.
"""

from modules.rag.retriever import HybridRetriever
from modules.rag.generator import LLMGenerator
from modules.rag.reranker import CrossEncoderReranker
from modules.rag.pre_retrieval import QueryProcessor, QueryTransformationType
from modules.rag.orchestration import QueryRouter, QueryType
from modules.config import RAGConfig
from modules.rag.memory import ConversationMemory
from typing import List


class ModularRAG:
    """
    Advanced Modular RAG system with configurable components.

    Implements the Modular RAG framework with:
    - Pre-retrieval: Query rewriting, expansion, HyDE, step-back, decomposition
    - Retrieval: Hybrid search (BM25 + dense), multi-query, RRF fusion
    - Orchestration: Adaptive routing, iterative refinement
    """

    def __init__(self, knowledge_file: str, config_path: str = None):
        self.config = RAGConfig(config_path) if config_path else None

        kb_context = self._get_config('knowledge_base', 'description',
                                      'team workspace with project information')

        print("Initializing Modular RAG System...")

        self.retriever = HybridRetriever(
            embedding_model=self._get_config('retriever', 'model', 'text-embedding-3-small'),
            dense_weight=self._get_config('retriever', 'dense_weight', 0.5),
            sparse_weight=self._get_config('retriever', 'sparse_weight', 0.5)
        )

        self.generator = LLMGenerator(
            model=self._get_config('generator', 'model', 'gpt-4o-mini'),
            knowledge_base_context=kb_context
        )

        max_history = self._get_config('memory', 'max_history', 10)
        self.memory = ConversationMemory(max_history=max_history)

        self.reranker = None
        if self._is_enabled('reranker'):
            self.reranker = CrossEncoderReranker(
                model_name=self._get_config('reranker', 'model', 'cross-encoder/ms-marco-MiniLM-L-6-v2')
            )

        self.query_processor = None
        if self._is_enabled('query_processor'):
            self.query_processor = QueryProcessor(
                enable_expansion=self._get_config('query_processor', 'expansion', True),
                enable_rewriting=self._get_config('query_processor', 'rewriting', True),
                enable_hyde=self._get_config('query_processor', 'hyde', False),
                enable_step_back=self._get_config('query_processor', 'step_back', False),
                enable_decomposition=self._get_config('query_processor', 'decomposition', False)
            )

        self.query_router = None
        max_iterations = self._get_config('orchestration', 'max_iterations', 3)
        if self._is_enabled('orchestration', 'routing_enabled'):
            self.query_router = QueryRouter(
                knowledge_base_context=kb_context,
                max_iterations=max_iterations
            )

        self.retriever.load_knowledge(knowledge_file)
        self.retriever.create_embeddings()

        print("Modular RAG System initialized successfully!")

    def _get_config(self, section: str, key: str, default):
        if self.config is None:
            return default
        section_config = getattr(self.config, f"{section}_config", {})
        return section_config.get(key, default)

    def _is_enabled(self, section: str, key: str = 'enabled'):
        if self.config is None:
            return False
        section_config = getattr(self.config, f"{section}_config", {})
        return section_config.get(key, False)

    def query(self, question: str, top_k: int = None, verbose: bool = True, return_chunks: bool = False):
        if verbose:
            print(f"\n{'='*60}")
            print(f"Question: {question}")
            print('='*60)

        query_type = None
        pipeline_config = {}

        if self.query_router:
            query_type = self.query_router.classify_query(question)
            pipeline_config = self.query_router.get_pipeline_config(query_type)

            if verbose:
                print(f"\n[Router] Query Type: {query_type.value}")
                if 'strategy' in pipeline_config:
                    print(f"[Router] Strategy: {pipeline_config['strategy']}")
        else:
            pipeline_config = {
                'use_query_processing': False,
                'retrieval_method': 'dense',
                'retrieval_top_k': top_k or self._get_config('retriever', 'top_k', 15),
                'use_reranking': self._is_enabled('reranker'),
                'reranker_top_n': self._get_config('reranker', 'top_n', 10)
            }

        conversation_context = None
        if self.memory.has_history():
            conversation_context = self.memory.get_contextual_summary(max_turns=3)
            if verbose and query_type == QueryType.CONVERSATIONAL:
                print(f"\n[Memory] Using context from {len(self.memory.get_last_n_turns(3))} previous turns")

        processed_result = {"processed_query": question, "hypothetical_doc": None, "sub_queries": [], "step_back_query": None}

        if pipeline_config.get('use_query_processing') and self.query_processor:
            strategies = self._get_strategies_for_config(pipeline_config)
            processed_result = self.query_processor.process(question, conversation_context, strategies)

            if verbose:
                print(f"\n[Pre-retrieval] Transformations: {processed_result['transformations_applied']}")
                if processed_result['processed_query'] != question:
                    print(f"[Pre-retrieval] Processed: {processed_result['processed_query']}")

        context_chunks = self._execute_retrieval(
            processed_result,
            pipeline_config,
            question,
            verbose
        )

        chunk_scores = []
        if pipeline_config.get('use_reranking') and self.reranker and context_chunks:
            reranker_top_n = pipeline_config.get('reranker_top_n', 3)
            reranked = self.reranker.rerank(
                question,
                [(chunk, 1.0) for chunk in context_chunks],
                top_n=reranker_top_n
            )
            context_chunks = [chunk for chunk, score in reranked]
            chunk_scores = [score for chunk, score in reranked]

            if verbose:
                print(f"\n[Reranker] Selected top {len(context_chunks)} documents")
        else:
            chunk_scores = [1.0] * len(context_chunks)

        if verbose:
            print("\n[Generator] Generating answer...")

        conversation_history = self.memory.get_full_history() if self.memory.has_history() else None
        answer = self.generator.generate(question, context_chunks, conversation_history)

        if self.query_router and pipeline_config.get('max_iterations', 1) > 1:
            answer = self._iterative_refinement(
                question,
                answer,
                context_chunks,
                query_type,
                pipeline_config,
                verbose
            )

        self.memory.add_turn(
            question=question,
            answer=answer,
            retrieved_context=context_chunks,
            metadata={
                'query_type': query_type.value if query_type else 'unknown',
                'processed_query': processed_result['processed_query'],
                'strategy': pipeline_config.get('strategy', 'default'),
                'num_context': len(context_chunks)
            }
        )

        if verbose:
            print(f"\n{'='*60}")
            print(f"Answer: {answer}")
            print('='*60)

        if return_chunks:
            chunks_data = []
            for i, chunk in enumerate(context_chunks):
                score = chunk_scores[i] if i < len(chunk_scores) else 1.0
                chunks_data.append({
                    "preview": chunk[:200] if len(chunk) > 200 else chunk,
                    "score": float(score)
                })
            return {
                "answer": answer,
                "chunks": chunks_data
            }

        return answer

    def _get_strategies_for_config(self, config: dict) -> List[QueryTransformationType]:
        strategies = []

        if config.get('use_query_processing'):
            strategies.extend([QueryTransformationType.REWRITE, QueryTransformationType.EXPAND])

        if config.get('use_hyde'):
            strategies.append(QueryTransformationType.HYDE)

        if config.get('use_step_back'):
            strategies.append(QueryTransformationType.STEP_BACK)

        if config.get('use_decomposition'):
            strategies.append(QueryTransformationType.DECOMPOSE)

        return strategies if strategies else None

    def _execute_retrieval(
        self,
        processed_result: dict,
        pipeline_config: dict,
        original_question: str,
        verbose: bool
    ) -> List[str]:
        retrieval_top_k = pipeline_config.get('retrieval_top_k', 5)
        retrieval_method = pipeline_config.get('retrieval_method', 'hybrid')

        all_chunks = []

        if processed_result.get('hypothetical_doc'):
            results = self.retriever.retrieve_with_hyde(
                processed_result['hypothetical_doc'],
                processed_result['processed_query'],
                top_k=retrieval_top_k
            )
            chunks = [chunk for chunk, _ in results]
            all_chunks.extend(chunks)
            if verbose:
                print(f"\n[Retriever] HyDE retrieval: {len(chunks)} documents")

        elif processed_result.get('sub_queries'):
            queries = [processed_result['processed_query']] + processed_result['sub_queries']
            results = self.retriever.multi_query_retrieve(
                queries,
                top_k=retrieval_top_k,
                method=retrieval_method
            )
            chunks = [chunk for chunk, _ in results]
            all_chunks.extend(chunks)
            if verbose:
                print(f"\n[Retriever] Multi-query retrieval ({len(queries)} queries): {len(chunks)} documents")

        else:
            results = self.retriever.retrieve(
                processed_result['processed_query'],
                top_k=retrieval_top_k,
                method=retrieval_method
            )
            chunks = [chunk for chunk, _ in results]
            all_chunks.extend(chunks)
            if verbose:
                print(f"\n[Retriever] {retrieval_method.capitalize()} retrieval: {len(chunks)} documents")

        if processed_result.get('step_back_query'):
            step_back_results = self.retriever.retrieve(
                processed_result['step_back_query'],
                top_k=3,
                method=retrieval_method
            )
            step_back_chunks = [chunk for chunk, _ in step_back_results]

            for chunk in step_back_chunks:
                if chunk not in all_chunks:
                    all_chunks.append(chunk)

            if verbose:
                print(f"[Retriever] Step-back retrieval: +{len(step_back_chunks)} background documents")

        seen = set()
        unique_chunks = []
        for chunk in all_chunks:
            if chunk not in seen:
                seen.add(chunk)
                unique_chunks.append(chunk)

        return unique_chunks

    def _iterative_refinement(
        self,
        original_question: str,
        initial_answer: str,
        context_chunks: List[str],
        query_type: QueryType,
        pipeline_config: dict,
        verbose: bool
    ) -> str:
        answer = initial_answer
        iteration = 1

        while self.query_router.should_iterate(query_type, iteration):
            quality = self.query_router.assess_answer_completeness(
                original_question,
                answer,
                context_chunks
            )

            if verbose:
                print(f"\n[Iteration {iteration}] Answer completeness: {quality:.2f}")

            if quality > 0.8:
                break

            refined_query = self.query_router.refine_query_for_iteration(
                original_question,
                answer,
                iteration
            )

            if verbose:
                print(f"[Iteration {iteration}] Refined query: {refined_query}")

            additional_results = self.retriever.retrieve(
                refined_query,
                top_k=pipeline_config.get('retrieval_top_k', 5),
                method='hybrid'
            )

            additional_chunks = [chunk for chunk, _ in additional_results]
            combined_chunks = context_chunks + [c for c in additional_chunks if c not in context_chunks]

            conversation_history = self.memory.get_full_history() if self.memory.has_history() else None
            answer = self.generator.generate(
                original_question,
                combined_chunks,
                conversation_history
            )

            context_chunks = combined_chunks
            iteration += 1

        return answer

    def get_pipeline_info(self) -> dict:
        return {
            "retriever": "Hybrid (BM25 + Dense)",
            "reranker": "Cross-Encoder" if self.reranker else "None",
            "query_processor": "Enabled (HyDE, Step-back, Decomposition)" if self.query_processor else "Disabled",
            "query_router": "Enabled (7 query types)" if self.query_router else "Disabled",
            "generator": f"LLM Generator ({self._get_config('generator', 'model', 'gpt-4o-mini')})",
            "memory": "Enabled"
        }

    def clear_conversation(self):
        self.memory.clear()
        print("Conversation history cleared")

    def get_conversation_stats(self) -> dict:
        return self.memory.get_session_stats()
