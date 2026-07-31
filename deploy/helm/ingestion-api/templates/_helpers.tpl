{{- define "ingestion-api.fullname" -}}
{{- .Release.Name }}-ingestion-api
{{- end }}

{{- define "ingestion-api.labels" -}}
app.kubernetes.io/name: ingestion-api
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "ingestion-api.selectorLabels" -}}
app.kubernetes.io/name: ingestion-api
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "ingestion-api.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "ingestion-api.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}
