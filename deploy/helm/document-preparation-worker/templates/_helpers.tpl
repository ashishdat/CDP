{{- define "document-preparation-worker.fullname" -}}
{{- .Release.Name }}-document-preparation-worker
{{- end }}

{{- define "document-preparation-worker.labels" -}}
app.kubernetes.io/name: document-preparation-worker
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "document-preparation-worker.selectorLabels" -}}
app.kubernetes.io/name: document-preparation-worker
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "document-preparation-worker.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "document-preparation-worker.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}
