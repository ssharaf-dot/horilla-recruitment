/* Saved sections, accessible optional templates and clear unsaved-work recovery. */
(function(){
  var form=document.querySelector('[data-requisition-form]');if(!form)return;
  var dirty=false,submitting=false,status=form.querySelector('[data-save-status]');
  function markDirty(){dirty=true;if(status)status.textContent='Unsaved changes · use Save & Next or Save & close';}
  function insert(field){if(!field || field.value.trim() || !field.dataset.template)return;field.value=field.dataset.template;field.dispatchEvent(new Event('input',{bubbles:true}));field.focus();}
  form.querySelectorAll('[data-template]').forEach(function(field){
    field.addEventListener('focus',function(){field.dataset.suggestion='yes';});
    field.addEventListener('keydown',function(event){
      if(event.key==='Escape'){field.dataset.suggestion='no';return;}
      if(event.key==='Tab'&&!event.shiftKey&&field.dataset.suggestion==='yes'&&!field.value.trim()){event.preventDefault();insert(field);field.dataset.suggestion='no';}
    });
  });
  form.querySelectorAll('[data-template-for]').forEach(function(button){button.addEventListener('click',function(){insert(document.getElementById(button.dataset.templateFor));});});
  function estimate(){var box=form.querySelector('[data-budget-estimate]');if(!box)return;var max=form.querySelector('[name="salary_max"]'),period=form.querySelector('[name="salary_period"]'),currency=form.querySelector('[name="salary_currency"]');var value=Number(max.value),count=Number(box.dataset.openings||1);if(Number.isFinite(value)&&value>0)box.textContent='Salary-only upper estimate: '+currency.value+' '+(value*(period.value==='month'?12:1)*count).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})+' for all '+count+' opening(s) over 12 months. Add costs excluded from the salary basis to your total budget and notes.';}
  form.addEventListener('input',function(event){markDirty();estimate();if(event.target.name==='jd_text'){var reviewed=form.querySelector('[name=jd_reviewed]');if(reviewed)reviewed.checked=false;}});form.addEventListener('change',function(){markDirty();estimate();});estimate();
  function announce(message){var box=document.getElementById('request-errors');if(!box){box=document.createElement('div');box.id='request-errors';box.className='wx-message error';box.setAttribute('role','alert');box.tabIndex=-1;form.prepend(box);}box.textContent=message;box.focus();}
  form.addEventListener('submit',async function(event){
    if(!window.fetch||!window.FormData)return;
    event.preventDefault();if(submitting)return;
    submitting=true;if(status)status.textContent='Saving…';
    var data=new FormData(form),button=event.submitter,buttons=Array.from(form.querySelectorAll('button[type="submit"],button[name="action"],button[name="decision"]'));
    if(button&&button.name)data.append(button.name,button.value);
    buttons.forEach(function(b){b.disabled=true;});
    try{
      var response=await fetch(form.getAttribute('action')||window.location.href,{method:'POST',body:data,credentials:'same-origin',cache:'no-store'});
      if(response.redirected){
        var destination=new URL(response.url);
        if(destination.pathname.includes('/login')){announce('Your session expired. Keep this page open, sign in in another tab, then retry. Your unsaved entries remain here.');return;}
        dirty=false;window.location.assign(response.url);return;
      }
      if(!response.ok){announce('The server could not confirm this save. Your entries remain here. Retry once; if this was a new draft, the same request will be reused rather than duplicated.');return;}
      var parsed=new DOMParser().parseFromString(await response.text(),'text/html'),errors=parsed.getElementById('request-errors')||parsed.querySelector('[data-requisition-form] [role=alert]')||parsed.querySelector('[data-requisition-form] .errorlist');
      if(errors){errors.id='request-errors';var current=document.getElementById('request-errors');if(current)current.remove();errors.tabIndex=-1;form.prepend(document.importNode(errors,true));form.querySelector('#request-errors').focus();}
      else announce('The save was not confirmed. Your entries remain here; review the form before retrying.');
    }catch(error){announce('Connection interrupted. Your entries remain here. Check your connection and retry. If the save already completed, the system will show the saved request or explain that a newer version exists.');}
    finally{submitting=false;buttons.forEach(function(b){b.disabled=false;});if(status)status.textContent='Not saved · check the message above';}
  });
  window.addEventListener('beforeunload',function(event){if(dirty&&!submitting){event.preventDefault();event.returnValue='';}});
  document.querySelectorAll('a').forEach(function(link){link.addEventListener('click',function(event){if(dirty&&!submitting){if(!window.confirm('You have unsaved changes. Stay on this page to use Save & Next or Save & close. Leave without saving?'))event.preventDefault();else dirty=false;}});});
  var errors=document.getElementById('request-errors');if(errors)errors.scrollIntoView({block:'start'});
})();
