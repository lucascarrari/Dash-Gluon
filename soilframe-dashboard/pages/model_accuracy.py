"""Métricas e gráficos calculados sobre previsões de teste do AutoML."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from soilframe_dashboard.data_access import detect_column
from soilframe_dashboard.metrics import format_metric_value
from soilframe_dashboard.ui import get_job_manager, page_header, render_geographic_filters


page_header(
    "Acurácia e confiabilidade do AutoML",
    "Métricas do conjunto de teste, gráficos diagnósticos e comparação dos modelos candidatos.",
)
render_geographic_filters()
app_root = Path(__file__).resolve().parents[1]
manager = get_job_manager(str(app_root / "outputs"))
runs = [
    run
    for run in manager.list_runs()
    if run["status"] == "completed"
    and run["task_type"] == "tabular"
    and run.get("predictions_path")
    and Path(run["predictions_path"]).is_file()
]
if not runs:
    st.info("Ainda não há modelos tabulares concluídos com previsões do conjunto de teste.")
    st.stop()

run_id = st.selectbox("Execução AutoML", [run["run_id"] for run in runs])
run = next(item for item in runs if item["run_id"] == run_id)
data = pd.read_csv(run["predictions_path"])
target = run["target"]
actual_column = target if target in data.columns else detect_column(
    list(data.columns), ("valor_real", "observado", "actual", "y_true")
)
predicted_column = f"previsao_{target}"
if predicted_column not in data.columns:
    candidates = [
        name for name in data.select_dtypes(include="number")
        if name.startswith("previsao_")
    ]
    predicted_column = candidates[0] if candidates else None
if actual_column is None or predicted_column is None:
    st.warning("Não encontrei no arquivo as colunas de valor observado e previsão.")
    st.stop()

problem_type = run.get("options", {}).get("problem_type", "regression")
data = data.dropna(subset=[actual_column, predicted_column]).copy()
if data.empty:
    st.warning("O conjunto de teste não contém pares completos de valores observados e previstos.")
    st.stop()

st.caption(f"Alvo: {target} · teste: {len(data):,} registros · execução {run_id}")

if problem_type == "regression":
    data["_actual"] = pd.to_numeric(data[actual_column], errors="coerce")
    data["_predicted"] = pd.to_numeric(data[predicted_column], errors="coerce")
    data = data.dropna(subset=["_actual", "_predicted"]).copy()
    if data.empty:
        st.warning("Os valores de regressão não são numéricos.")
        st.stop()
    data["Erro"] = data["_predicted"] - data["_actual"]
    data["Erro absoluto"] = data["Erro"].abs()
    mae = float(data["Erro absoluto"].mean())
    mse = float(np.square(data["Erro"]).mean())
    rmse = float(np.sqrt(mse))
    denominator = float(np.square(data["_actual"] - data["_actual"].mean()).sum())
    r2 = float(1 - np.square(data["Erro"]).sum() / denominator) if denominator else float("nan")
    st.subheader("Desempenho do melhor modelo no conjunto de teste")
    st.caption("Regressão não tem uma acurácia percentual única. As métricas abaixo são recalculadas comparando cada previsão com seu valor observado.")
    cards = st.columns(4)
    cards[0].metric("MAE", format_metric_value("mae", mae), help="Erro absoluto médio, na unidade do alvo; menor é melhor.")
    cards[1].metric("MSE", format_metric_value("mse", mse), help="Erro quadrático médio; penaliza erros maiores.")
    cards[2].metric("RMSE", format_metric_value("rmse", rmse), help="Raiz do erro quadrático médio, na unidade do alvo; menor é melhor.")
    cards[3].metric("R²", format_metric_value("r2", r2), help="1 indica ajuste perfeito; pode ser negativo.")
    left, right = st.columns(2)
    with left:
        fig = px.scatter(data, x="_actual", y="_predicted", opacity=0.65,
                         labels={"_actual": "Valor observado", "_predicted": "Valor previsto"},
                         title="Previsto versus observado")
        low = float(min(data["_actual"].min(), data["_predicted"].min()))
        high = float(max(data["_actual"].max(), data["_predicted"].max()))
        fig.add_shape(type="line", x0=low, y0=low, x1=high, y1=high,
                      line={"color": "#e45756", "dash": "dash"})
        fig.update_layout(separators=",.", showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    with right:
        fig = px.scatter(data, x="_predicted", y="Erro", opacity=0.65,
                         title="Gráfico de resíduos",
                         labels={"_predicted": "Valor previsto", "Erro": "Previsto − observado"})
        fig.add_hline(y=0, line_dash="dash", line_color="#e45756")
        fig.update_layout(separators=",.")
        st.plotly_chart(fig, use_container_width=True)
    fig = px.histogram(data, x="Erro", nbins=40, title="Distribuição dos erros")
    fig.add_vline(x=0, line_dash="dash", line_color="#e45756")
    fig.update_layout(separators=",.")
    st.plotly_chart(fig, use_container_width=True)
else:
    from sklearn.metrics import (
        accuracy_score,
        average_precision_score,
        confusion_matrix,
        f1_score,
        precision_recall_curve,
        precision_score,
        recall_score,
        roc_auc_score,
        roc_curve,
    )
    from sklearn.calibration import calibration_curve

    actual = data[actual_column].astype(str)
    predicted = data[predicted_column].astype(str)
    labels = sorted(pd.unique(pd.concat([actual, predicted])).tolist())
    accuracy = float(accuracy_score(actual, predicted))
    precision = float(precision_score(actual, predicted, average="weighted", zero_division=0))
    recall = float(recall_score(actual, predicted, average="weighted", zero_division=0))
    f1 = float(f1_score(actual, predicted, average="weighted", zero_division=0))
    matrix = confusion_matrix(actual, predicted, labels=labels)
    specificities = []
    for index in range(len(labels)):
        tp = int(matrix[index, index])
        fn = int(matrix[index, :].sum() - tp)
        fp = int(matrix[:, index].sum() - tp)
        tn = int(matrix.sum() - tp - fn - fp)
        if tn + fp:
            specificities.append(tn / (tn + fp))
    specificity = float(np.mean(specificities)) if specificities else float("nan")

    st.subheader("Desempenho do melhor modelo no conjunto de teste")
    cards = st.columns(5)
    cards[0].metric("Acurácia", f"{accuracy:.1%}")
    cards[1].metric("Precisão ponderada", f"{precision:.1%}")
    cards[2].metric("Recall ponderado", f"{recall:.1%}")
    cards[3].metric("F1 ponderado", f"{f1:.1%}")
    cards[4].metric("Especificidade macro", f"{specificity:.1%}")

    matrix_fig = go.Figure(go.Heatmap(
        z=matrix, x=[str(value) for value in labels], y=[str(value) for value in labels],
        colorscale="Blues", text=matrix, texttemplate="%{text}",
    ))
    matrix_fig.update_layout(title="Matriz de confusão", xaxis_title="Classe prevista",
                             yaxis_title="Classe observada")
    st.plotly_chart(matrix_fig, use_container_width=True)

    class_names = run.get("metrics", {}).get("probability_classes", [])
    probability_columns = [f"probability_{index}" for index in range(len(class_names))]
    if len(class_names) >= 2 and all(column in data for column in probability_columns):
        probabilities = data[probability_columns].apply(pd.to_numeric, errors="coerce")
        valid = probabilities.notna().all(axis=1)
        probability_data = data.loc[valid]
        probabilities = probabilities.loc[valid].to_numpy()
        actual_valid = probability_data[actual_column].astype(str).to_numpy()
        class_names = [str(value) for value in class_names]
        binary = len(class_names) == 2
        roc_fig = go.Figure()
        pr_fig = go.Figure()
        calibration_fig = go.Figure()
        auc_values = []
        average_precision_values = []
        for index, class_name in enumerate(class_names):
            truth = (actual_valid == class_name).astype(int)
            if truth.min() == truth.max():
                continue
            score = probabilities[:, index]
            fpr, tpr, _ = roc_curve(truth, score)
            roc_value = float(roc_auc_score(truth, score))
            precision_curve, recall_curve, _ = precision_recall_curve(truth, score)
            roc_fig.add_trace(go.Scatter(x=fpr, y=tpr, mode="lines",
                                         name=f"{class_name} · AUC {roc_value:.3f}"))
            pr_fig.add_trace(go.Scatter(x=recall_curve, y=precision_curve, mode="lines",
                                        name=class_name))
            fraction_positive, mean_probability = calibration_curve(
                truth, score, n_bins=10, strategy="quantile"
            )
            calibration_fig.add_trace(go.Scatter(x=mean_probability, y=fraction_positive,
                                                 mode="lines+markers", name=class_name))
            auc_values.append(roc_value)
            average_precision_values.append(float(average_precision_score(truth, score)))
        if auc_values:
            metrics_columns = st.columns(2)
            metrics_columns[0].metric("ROC-AUC" if binary else "ROC-AUC macro OvR", f"{np.mean(auc_values):.3f}")
            metrics_columns[1].metric("Área média precisão-recall", f"{np.mean(average_precision_values):.3f}")
            roc_fig.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines",
                                         line={"dash": "dash", "color": "gray"},
                                         name="Referência aleatória"))
            roc_fig.update_layout(title="Curva ROC", xaxis_title="Taxa de falsos positivos",
                                  yaxis_title="Sensibilidade (recall)")
            pr_fig.update_layout(title="Curva precisão-recall", xaxis_title="Recall",
                                 yaxis_title="Precisão")
            calibration_fig.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines",
                                                  line={"dash": "dash", "color": "gray"},
                                                  name="Calibração ideal"))
            calibration_fig.update_layout(title="Curva de calibração",
                                          xaxis_title="Probabilidade média prevista",
                                          yaxis_title="Frequência positiva observada")
            chart_columns = st.columns(2)
            with chart_columns[0]:
                st.plotly_chart(roc_fig, use_container_width=True)
                st.plotly_chart(calibration_fig, use_container_width=True)
            with chart_columns[1]:
                st.plotly_chart(pr_fig, use_container_width=True)
        else:
            st.info("As classes do teste não permitem calcular ROC-AUC ou curvas precisão-recall.")
    else:
        st.info("Esta execução não salvou probabilidades por classe. ROC, precisão-recall e calibração estarão disponíveis para treinos iniciados após a atualização.")

leaderboard_path = run.get("leaderboard_path")
if leaderboard_path and Path(leaderboard_path).is_file():
    leaderboard = pd.read_csv(leaderboard_path)
    st.subheader("Comparação dos modelos candidatos do AutoML")
    if problem_type == "regression" and "mae_test" in leaderboard:
        compare_column = "mae_test"
        title = "MAE no conjunto de teste por modelo (menor é melhor)"
    elif problem_type != "regression" and "accuracy_test" in leaderboard:
        compare_column = "accuracy_test"
        title = "Acurácia no conjunto de teste por modelo"
    else:
        compare_column = None
        title = "Leaderboard AutoGluon"
    if compare_column:
        ranking = leaderboard.dropna(subset=[compare_column]).sort_values(
            compare_column,
            ascending=problem_type == "regression",
        )
        fig = px.bar(ranking, x="model", y=compare_column, title=title,
                     labels={"model": "Modelo AutoML", compare_column: compare_column})
        st.plotly_chart(fig, use_container_width=True)
    st.caption("Comparação recalculada para cada modelo candidato usando as mesmas observações do conjunto de teste.")
    st.caption("Como vários candidatos são comparados no mesmo teste, use o gráfico para diagnóstico. Para publicar uma estimativa final após escolher um candidato, avalie-o também em uma amostra externa que não participou desta comparação.")
    st.dataframe(leaderboard, use_container_width=True, hide_index=True)
else:
    st.info("O leaderboard desta execução não está disponível.")

st.subheader("Estabilidade da avaliação entre sementes de divisão")
snapshot = run.get("options", {}).get("dataset_snapshot", {})
fingerprint = snapshot.get("fingerprint_sha256")
strategy = run.get("options", {}).get("validation_strategy")
stability_metric = "rmse" if problem_type == "regression" else "accuracy"
if fingerprint and strategy == "localidade":
    comparable_runs = []
    for item in runs:
        options = item.get("options", {})
        item_metrics = item.get("metrics", {})
        item_snapshot = options.get("dataset_snapshot", {})
        if (
            item["target"] == target
            and options.get("problem_type") == problem_type
            and options.get("validation_strategy") == strategy
            and item_snapshot.get("fingerprint_sha256") == fingerprint
            and item_metrics.get(stability_metric) is not None
        ):
            comparable_runs.append(
                {
                    "Semente": int(item_metrics.get("random_state", options.get("random_state", 42))),
                    "Execução": item["run_id"],
                    "Resultado": float(item_metrics[stability_metric]),
                }
            )
    stability = pd.DataFrame(comparable_runs).drop_duplicates("Semente")
    if len(stability) >= 2:
        st.caption("A semente varia a separação de localidades entre treino e teste; ela não altera a aleatoriedade interna do ajuste AutoGluon.")
        mean_value = float(stability["Resultado"].mean())
        std_value = float(stability["Resultado"].std(ddof=1))
        stability_cards = st.columns(2)
        stability_cards[0].metric(f"Média de {stability_metric.upper()}", format_metric_value(stability_metric, mean_value))
        stability_cards[1].metric("Desvio padrão", format_metric_value(stability_metric, std_value),
                                  help="Calculado entre execuções com o mesmo conjunto de dados e sementes diferentes.")
        fig = px.box(stability, y="Resultado", points="all",
                     hover_data=["Semente", "Execução"],
                     title=f"Dispersão de {stability_metric.upper()} por semente")
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(stability.sort_values("Semente"), use_container_width=True, hide_index=True)
    else:
        st.info("Treine novamente com o mesmo conjunto e sementes diferentes para calcular média, desvio padrão e boxplot.")
elif strategy == "temporal":
    st.info("A divisão temporal usa o mesmo corte independentemente da semente. A estabilidade por sementes só é calculada na divisão por localidade.")
else:
    st.info("Não há identificação do conjunto de dados nesta execução para comparar estabilidade com segurança.")

date_column = detect_column(list(data.columns), ("data", "date", "timestamp", "datetime"))
if problem_type == "regression" and date_column:
    timeline = data.copy()
    timeline[date_column] = pd.to_datetime(timeline[date_column], errors="coerce")
    timeline = timeline.dropna(subset=[date_column]).sort_values(date_column)
    if not timeline.empty:
        fig = px.line(timeline, x=date_column, y="Erro absoluto",
                      title="Erro absoluto ao longo das datas de teste")
        st.plotly_chart(fig, use_container_width=True)

st.markdown("#### Resultados avaliados")
context_columns = [column for column in (date_column, "location_name", "state") if column and column in data]
value_columns = [actual_column, predicted_column]
if problem_type == "regression":
    value_columns.append("Erro")
else:
    value_columns.extend(column for column in data if column.startswith("probability_"))
st.dataframe(data[context_columns + value_columns].head(500), use_container_width=True, hide_index=True)

st.info("Curvas de loss por época e learning curves por volume de treino exigem refazer o ajuste em etapas e registrar o histórico de validação; o treinamento AutoGluon atual não gera esses artefatos. A estabilidade por sementes aparece acima quando existem execuções repetidas com o mesmo conjunto e divisão por localidade.")
