{{/*
Expand the name of the chart.
*/}}
{{- define "atulya.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "atulya.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "atulya.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "atulya.labels" -}}
helm.sh/chart: {{ include "atulya.chart" . }}
{{ include "atulya.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "atulya.selectorLabels" -}}
app.kubernetes.io/name: {{ include "atulya.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
API labels
*/}}
{{- define "atulya.api.labels" -}}
{{ include "atulya.labels" . }}
app.kubernetes.io/component: api
{{- end }}

{{/*
API selector labels
*/}}
{{- define "atulya.api.selectorLabels" -}}
{{ include "atulya.selectorLabels" . }}
app.kubernetes.io/component: api
{{- end }}

{{/*
Control plane labels
*/}}
{{- define "atulya.controlPlane.labels" -}}
{{ include "atulya.labels" . }}
app.kubernetes.io/component: control-plane
{{- end }}

{{/*
Control plane selector labels
*/}}
{{- define "atulya.controlPlane.selectorLabels" -}}
{{ include "atulya.selectorLabels" . }}
app.kubernetes.io/component: control-plane
{{- end }}

{{/*
Worker labels
*/}}
{{- define "atulya.worker.labels" -}}
{{ include "atulya.labels" . }}
app.kubernetes.io/component: worker
{{- end }}

{{/*
Worker selector labels
*/}}
{{- define "atulya.worker.selectorLabels" -}}
{{ include "atulya.selectorLabels" . }}
app.kubernetes.io/component: worker
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "atulya.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "atulya.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Generate database URL
*/}}
{{- define "atulya.databaseUrl" -}}
{{- if .Values.databaseUrl }}
{{- .Values.databaseUrl }}
{{- else if .Values.postgresql.enabled }}
{{- printf "postgresql://%s:%s@%s-postgresql:%d/%s" .Values.postgresql.auth.username .Values.postgresql.auth.password (include "atulya.fullname" .) (.Values.postgresql.service.port | int) .Values.postgresql.auth.database }}
{{- else }}
{{- printf "postgresql://%s:$(POSTGRES_PASSWORD)@%s:%d/%s" .Values.postgresql.external.username .Values.postgresql.external.host (.Values.postgresql.external.port | int) .Values.postgresql.external.database }}
{{- end }}
{{- end }}

{{/*
API URL for control plane
*/}}
{{- define "atulya.apiUrl" -}}
{{- printf "http://%s-api:%d" (include "atulya.fullname" .) (.Values.api.service.port | int) }}
{{- end }}

{{/*
TEI reranker labels
*/}}
{{- define "atulya.tei.reranker.labels" -}}
{{ include "atulya.labels" . }}
app.kubernetes.io/component: tei-reranker
{{- end }}

{{/*
TEI reranker selector labels
*/}}
{{- define "atulya.tei.reranker.selectorLabels" -}}
{{ include "atulya.selectorLabels" . }}
app.kubernetes.io/component: tei-reranker
{{- end }}

{{/*
TEI embedding labels
*/}}
{{- define "atulya.tei.embedding.labels" -}}
{{ include "atulya.labels" . }}
app.kubernetes.io/component: tei-embedding
{{- end }}

{{/*
TEI embedding selector labels
*/}}
{{- define "atulya.tei.embedding.selectorLabels" -}}
{{ include "atulya.selectorLabels" . }}
app.kubernetes.io/component: tei-embedding
{{- end }}

{{/*
Get the name of the secret to use
*/}}
{{- define "atulya.secretName" -}}
{{- if .Values.existingSecret }}
{{- .Values.existingSecret }}
{{- else }}
{{- printf "%s-secret" (include "atulya.fullname" .) }}
{{- end }}
{{- end }}
